import hashlib
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.activity_logs.services import record_event
from apps.common.constants import ROSARIO_COMMODITY_VALUES, commodity_category
from apps.crops.models import CropRecord
from apps.farm_parcels.coordinate_services import format_coordinates
from apps.farm_parcels.models import FarmParcel
from apps.ocr import services as ocr
from apps.ocr.conf import ocr_setting
from apps.ocr.exceptions import OcrUnavailable
from apps.ocr.imaging import ALLOWED_FORMATS

from .models import FieldCorrection, FormScan, FormScanAudit
from .validation import normalize_barangay, parse_area_hectares, validate

MIN_SIDE_PIXELS = 400
OWNERSHIP_CODES = {code: code for code, _ in FarmParcel.OWNERSHIP_CHOICES}
OWNERSHIP_WORDS = {
    "owner": "OWNED", "owned": "OWNED", "registered owner": "OWNED",
    "tenant": "TENANT", "lessee": "LEASED", "leased": "LEASED",
    "arb": "ARB", "agrarian reform beneficiary": "ARB", "other": "OTHER",
}


class ScanError(Exception):
    """A problem the staff member can fix; the message is shown to them."""


def read_upload(upload):
    """Validate type and size by content (not by name or declared type); return the bytes."""
    limit = ocr_setting("MAX_IMAGE_BYTES")
    if upload.size > limit:
        raise ScanError(f"The photo must be {limit // (1024 * 1024)} MB or smaller.")
    raw = upload.read()
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image_format, width, height = image.format, *image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ScanError("That file is not a readable JPG, PNG or WebP photo.")
    if image_format not in ALLOWED_FORMATS:
        raise ScanError("Only JPG, PNG or WebP photos can be scanned.")
    if min(width, height) < MIN_SIDE_PIXELS:
        raise ScanError(f"The photo is too small. Use one at least {MIN_SIDE_PIXELS} pixels on the short side.")
    return raw


def log(scan, actor, action, **detail):
    """Append one audit entry."""
    return FormScanAudit.objects.create(scan=scan, actor=actor, action=action, detail=detail)


def confidence_map(scan):
    return {name: entry.get("confidence") for name, entry in scan.ocr_fields.items()}


def run_validation(scan, values=None):
    """Validate the working values and store the traffic light on the scan."""
    values = scan.fields if values is None else values
    result = validate(
        values, confidence_map(scan), polygon=scan.drawn_polygon, exclude_parcel_pk=scan.parcel_id
    )
    scan.traffic_light = result.status
    scan.checks = [check.as_dict() for check in result.checks]
    return result


def normalize_ownership(text):
    """Map a written tenure to a model code, or '' when it is unclear."""
    text = (text or "").strip()
    return OWNERSHIP_CODES.get(text.upper()) or OWNERSHIP_WORDS.get(text.casefold(), "")


@transaction.atomic
def create_scan(user, upload):
    """Store the photo privately, ask OCR, and fall back to manual entry when OCR cannot answer."""
    raw = read_upload(upload)
    scan = FormScan(created_by=user, image_sha256=hashlib.sha256(raw).hexdigest())
    scan.image.save("scan.img", ContentFile(raw), save=False)
    names = ocr_setting("FIELDS")
    scan.fields = {name: "" for name in names}
    try:
        result = ocr.extract(raw)
    except OcrUnavailable as error:
        scan.ocr_message = str(error)[:500]
        scan.save()
        log(scan, user, "UPLOADED")
        log(scan, user, "OCR_UNAVAILABLE", reason=scan.ocr_message)
    else:
        scan.ocr_available = True
        scan.ocr_provider, scan.ocr_model = result.provider, result.model
        scan.ocr_fields = {n: {"value": r.value, "confidence": r.confidence} for n, r in result.fields.items()}
        scan.fields = {n: r.value for n, r in result.fields.items()}
        scan.fields["ownership_type"] = normalize_ownership(scan.fields.get("ownership_type", ""))
        scan.save()
        log(scan, user, "UPLOADED")
        log(scan, user, "OCR_DONE", provider=result.provider, model=result.model, fallbacks=result.attempts)
    run_validation(scan)
    scan.save(update_fields=["traffic_light", "checks"])
    return scan


def recheck(scan, user, values):
    """Store edited values and re-run the rules; log it when something changed."""
    changed = {k: v for k, v in values.items() if scan.fields.get(k, "") != v}
    scan.fields = {**scan.fields, **values}
    result = run_validation(scan)
    scan.save(update_fields=["fields", "traffic_light", "checks"])
    if changed:
        log(scan, user, "CHECKED", changed=list(changed), status=result.status)
    return result


def _commodity_value(text):
    lookup = {value.casefold(): value for value in ROSARIO_COMMODITY_VALUES}
    return lookup.get((text or "").strip().casefold())


@transaction.atomic
def approve_scan(scan, user, values, farmer):
    """Save the confirmed values as a farm parcel. RED results can never reach here."""
    scan = FormScan.objects.select_for_update().get(pk=scan.pk)
    if scan.status != FormScan.STATUS_DRAFT:
        raise ScanError("This scan has already been finished.")
    scan.fields = {**scan.fields, **values}
    result = run_validation(scan)
    if result.blocks_approval:
        scan.save(update_fields=["fields", "traffic_light", "checks"])
        raise ScanError("Red checks must be corrected before this record can be approved.")
    barangay, _ = normalize_barangay(values.get("barangay", ""))
    if barangay is None:
        raise ScanError("Choose a valid Rosario barangay before approving.")
    hectares, _ = parse_area_hectares(values.get("area_hectares", ""))
    area = Decimal(str(hectares or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if area <= 0:
        raise ScanError("Enter the farm area in hectares before approving.")
    ownership = normalize_ownership(values.get("ownership_type", ""))
    if not ownership:
        raise ScanError("Choose the ownership type before approving.")

    parcel = FarmParcel.objects.create(
        farmer=farmer, parcel_name=values.get("parcel_name", "")[:120], barangay=barangay,
        area_hectares=area, ownership_type=ownership,
        coordinates=format_coordinates(*result.point) if result.point else "",
        remarks=f"Created from Scan & Auto-Fill #{scan.pk}",
    )
    commodity = _commodity_value(values.get("commodity"))
    crop_added = bool(commodity and commodity_category(commodity) == "crop")
    if crop_added:
        CropRecord.objects.create(parcel=parcel, crop_type=commodity, area_hectares=area)

    changed = _record_corrections(scan, user, values)
    now = timezone.now()
    scan.status, scan.farmer, scan.parcel = FormScan.STATUS_APPROVED, farmer, parcel
    scan.approved_by, scan.approved_at = user, now
    scan.save()
    log(
        scan, user, "APPROVED", provider=scan.ocr_provider, model=scan.ocr_model,
        status=result.status, parcel=parcel.pk, commodity_added=crop_added,
        ocr={n: e["value"] for n, e in scan.ocr_fields.items()}, final=values, changed=changed,
        converted_from_dms=bool(result.suggested_point and result.point == result.suggested_point),
    )
    record_event(
        actor=user, title="Farm Parcel Created from Scan", module="Farm Parcels",
        description=f"{user.display_name} approved a scanned form as a farm parcel (traffic light {result.status}).",
        path=f"/scan/{scan.pk}/", target_label=parcel.display_name,
        details=[{"field": name, "before": scan.ocr_fields.get(name, {}).get("value", ""), "after": values.get(name, "")} for name in changed],
    )
    return parcel


def _record_corrections(scan, user, values):
    """Keep every changed OCR value next to its final value for later learning."""
    changed = []
    if not scan.ocr_available:
        return changed
    for name, entry in scan.ocr_fields.items():
        original, final = entry.get("value", "").strip(), values.get(name, "").strip()
        if original != final:
            changed.append(name)
            FieldCorrection.objects.create(
                scan=scan, field_name=name, ocr_value=original, final_value=final,
                confidence=entry.get("confidence"), ocr_provider=scan.ocr_provider,
                ocr_model=scan.ocr_model, corrected_by=user,
            )
    return changed


def discard_scan(scan, user):
    """Mark a draft as discarded; the audit trail and image are kept."""
    if scan.status != FormScan.STATUS_DRAFT:
        raise ScanError("This scan has already been finished.")
    scan.status = FormScan.STATUS_DISCARDED
    scan.save(update_fields=["status"])
    log(scan, user, "DISCARDED")
