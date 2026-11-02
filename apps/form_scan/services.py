import hashlib
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.activity_logs.services import record_event
from apps.common.constants import ROSARIO_COMMODITY_VALUES
from apps.farm_parcels.coordinate_services import format_coordinates, parse_coordinates
from apps.farm_parcels.models import FarmParcel
from apps.ocr import services as ocr
from apps.ocr.conf import ocr_setting
from apps.ocr.exceptions import OcrUnavailable
from apps.ocr.imaging import ALLOWED_FORMATS

from .models import FieldCorrection, FormScan, FormScanAudit
from .validation import RED, normalize_barangay, parse_area_hectares, validate

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
def create_scan(user, upload, target=FormScan.TARGET_PARCEL):
    """Store the photo privately, ask OCR, and fall back to manual entry when OCR cannot answer."""
    raw = read_upload(upload)
    scan = FormScan(created_by=user, image_sha256=hashlib.sha256(raw).hexdigest(), target=target)
    scan.image.save("scan.img", ContentFile(raw), save=False)
    names = ocr_setting("FIELDS")
    scan.fields = {name: "" for name in names}
    try:
        result = ocr.extract(raw)
    except OcrUnavailable as error:
        scan.ocr_message = str(error)[:500]
        scan.save()
        log(scan, user, "UPLOADED", target=target)
        log(scan, user, "OCR_UNAVAILABLE", reason=scan.ocr_message)
    else:
        scan.ocr_available = True
        scan.ocr_provider, scan.ocr_model = result.provider, result.model
        scan.ocr_fields = {n: {"value": r.value, "confidence": r.confidence} for n, r in result.fields.items()}
        scan.fields = {n: r.value for n, r in result.fields.items()}
        scan.fields["ownership_type"] = normalize_ownership(scan.fields.get("ownership_type", ""))
        scan.save()
        log(scan, user, "UPLOADED", target=target)
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


def commodity_value(text):
    """The official commodity name for what was written, or None."""
    lookup = {value.casefold(): value for value in ROSARIO_COMMODITY_VALUES}
    return lookup.get((text or "").strip().casefold())


def _hectares_text(text):
    hectares, _ = parse_area_hectares(text or "")
    return f"{hectares:.2f}" if hectares and hectares > 0 else ""


@transaction.atomic
def confirm_scan(scan, user, values, farmer=None):
    """Staff confirm the values; they are then entered in the target form, ready to save.

    A red result can never be confirmed. Nothing is written to the farm records here.
    """
    scan = FormScan.objects.select_for_update().get(pk=scan.pk)
    if scan.status not in (FormScan.STATUS_DRAFT, FormScan.STATUS_CONFIRMED):
        raise ScanError("This scan has already been finished.")
    scan.fields = {**scan.fields, **values}
    result = run_validation(scan)
    if result.blocks_approval:
        scan.save(update_fields=["fields", "traffic_light", "checks"])
        raise ScanError("Red checks must be corrected before this scan can be confirmed.")
    area = _hectares_text(values.get("area_hectares"))
    if scan.target == FormScan.TARGET_PARCEL:
        barangay, _ = normalize_barangay(values.get("barangay", ""))
        if barangay is None:
            raise ScanError("Choose a valid Rosario barangay before confirming.")
        if not area:
            raise ScanError("Enter the farm area in hectares before confirming.")
        scan.prefill = {
            "farmer": farmer.pk if farmer else "", "barangay": barangay, "area_hectares": area,
            "ownership_type": normalize_ownership(values.get("ownership_type", "")),
            "coordinates": format_coordinates(*result.point) if result.point else "",
        }
    else:
        commodity = commodity_value(values.get("commodity"))
        if commodity is None:
            raise ScanError("Choose a commodity from the list before confirming.")
        scan.prefill = {"crop_type": commodity, "area_hectares": area}
    scan.farmer = farmer
    scan.status, scan.approved_by, scan.approved_at = FormScan.STATUS_CONFIRMED, user, timezone.now()
    scan.save()
    log(scan, user, "CONFIRMED", status=result.status, prefill=scan.prefill,
        converted_from_dms=bool(result.suggested_point and result.point == result.suggested_point))
    return scan


def blocking_problem(scan, form_values):
    """Re-run the rules on what is about to be saved; return a message when it is red."""
    result = validate(form_values, None, exclude_parcel_pk=None)
    if result.status != RED:
        return ""
    first = next(check for check in result.checks if check.level == "fail")
    return f"The scan check is red: {first.message}"


def saved_values(obj):
    """The comparable values of a record saved from a scan, by scan field name."""
    if isinstance(obj, FarmParcel):
        point = parse_coordinates(obj.coordinates)
        return {
            "barangay": obj.barangay, "area_hectares": f"{obj.area_hectares:.2f}",
            "ownership_type": obj.ownership_type,
            "latitude": f"{point[0]:.6f}" if point else "", "longitude": f"{point[1]:.6f}" if point else "",
        }
    return {"commodity": obj.crop_type, "area_hectares": f"{obj.area_hectares:.2f}" if obj.area_hectares else ""}


def _same(name, ocr_value, final_value):
    if name in ("latitude", "longitude", "area_hectares"):
        try:
            return abs(float(ocr_value) - float(final_value)) < 1e-6
        except ValueError:
            return False
    return ocr_value.casefold() == final_value.casefold()


@transaction.atomic
def finalize_scan(scan, user, obj):
    """The target form saved a record: link it, keep what staff changed, and close the audit trail."""
    scan = FormScan.objects.select_for_update().get(pk=scan.pk)
    if scan.status != FormScan.STATUS_CONFIRMED:
        return None
    final = saved_values(obj)
    changed = []
    if scan.ocr_available:
        for name, value in final.items():
            original = scan.ocr_fields.get(name, {}).get("value", "").strip()
            if name not in scan.ocr_fields or _same(name, original, value):
                continue
            changed.append(name)
            FieldCorrection.objects.create(
                scan=scan, field_name=name, ocr_value=original, final_value=value,
                confidence=scan.ocr_fields[name].get("confidence"), ocr_provider=scan.ocr_provider,
                ocr_model=scan.ocr_model, corrected_by=user,
            )
    if isinstance(obj, FarmParcel):
        scan.parcel, scan.farmer = obj, obj.farmer
    else:
        scan.crop, scan.parcel = obj, obj.parcel
        scan.farmer = obj.parcel.farmer
    scan.status = FormScan.STATUS_APPROVED
    scan.save()
    log(scan, user, "SAVED", record=str(obj), provider=scan.ocr_provider, model=scan.ocr_model,
        ocr={n: e["value"] for n, e in scan.ocr_fields.items()}, final=final, changed=changed,
        approved_by=scan.approved_by.display_name if scan.approved_by else "")
    record_event(
        actor=user, title="Record Saved from Scan", module="Scan & Auto-Fill",
        description=f"{user.display_name} saved a record filled in from a scanned form (traffic light {scan.traffic_light}).",
        path=f"/scan/{scan.pk}/", target_label=str(obj),
        details=[{"field": name, "before": scan.ocr_fields.get(name, {}).get("value", ""), "after": final[name]} for name in changed],
    )
    return scan


def discard_scan(scan, user):
    """Mark an unsaved scan as discarded; the audit trail and image are kept."""
    if scan.status not in (FormScan.STATUS_DRAFT, FormScan.STATUS_CONFIRMED):
        raise ScanError("This scan has already been finished.")
    scan.status = FormScan.STATUS_DISCARDED
    scan.save(update_fields=["status"])
    log(scan, user, "DISCARDED")
