import hashlib
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.activity_logs.services import record_event
from apps.common.constants import ROSARIO_COMMODITY_VALUES
from apps.farm_parcels.coordinate_services import format_coordinates, parse_coordinates
from apps.farm_parcels.models import FarmParcel
from apps.ocr import services as ocr
from apps.ocr.conf import ocr_setting
from apps.ocr.exceptions import OcrAllModelsFailed, OcrQuotaExceeded, OcrUnavailable, UploadRejected
from apps.ocr.uploads import read_uploads

from .events import scan_event, warn_admins_once
from .models import FieldCorrection, FormScan, FormScanAudit, FormScanPage
from .validation import RED, normalize_barangay, parse_area_hectares, validate

OWNERSHIP_CODES = {code: code for code, _ in FarmParcel.OWNERSHIP_CHOICES}
OWNERSHIP_WORDS = {
    "owner": "OWNED", "owned": "OWNED", "registered owner": "OWNED",
    "tenant": "TENANT", "lessee": "LEASED", "leased": "LEASED",
    "arb": "ARB", "agrarian reform beneficiary": "ARB", "other": "OTHER",
}


# Values staff accept or reject together. Latitude and longitude are one decision (the location).
GROUPS = {
    "barangay": ("barangay",),
    "location": ("latitude", "longitude"),
    "area_hectares": ("area_hectares",),
    "ownership_type": ("ownership_type",),
    "commodity": ("commodity",),
}
TARGET_GROUPS = {
    FormScan.TARGET_PARCEL: ("barangay", "location", "area_hectares", "ownership_type"),
    FormScan.TARGET_CROP: ("commodity", "area_hectares"),
}


class ScanError(Exception):
    """A problem the staff member can fix; the message is shown to them."""


def log(scan, actor, action, **detail):
    """Append one audit entry."""
    return FormScanAudit.objects.create(scan=scan, actor=actor, action=action, detail=detail)


def confidence_map(scan):
    return {name: entry.get("confidence") for name, entry in scan.ocr_fields.items()}


def effective_values(rejected_groups, values):
    """The values the rules and the form see: rejected groups count as not written."""
    hidden = {name for group in rejected_groups for name in GROUPS.get(group, ())}
    return {name: ("" if name in hidden else value) for name, value in values.items()}


def run_validation(scan, values=None):
    """Validate the working values (minus rejected groups) and store the traffic light on the scan."""
    values = effective_values(scan.rejected_groups, scan.fields if values is None else values)
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


def purge_files(scan, reason="Scan finished"):
    """Delete every stored photo of a scan. The text audit trail and corrections are kept."""
    removed = 0
    for page in list(scan.extra_pages.all()):
        if page.image:
            page.image.storage.delete(page.image.name)
            removed += 1
        page.delete()
    if scan.image:
        scan.image.storage.delete(scan.image.name)
        scan.image = ""
        removed += 1
    if scan.files_deleted_at is None:
        scan.files_deleted_at = timezone.now()
    scan.save(update_fields=["image", "files_deleted_at", "updated_at"])
    if removed:
        log(scan, None, "FILES_DELETED", photos=removed, reason=reason)
    return removed


def expire_stale_scans(hours=None):
    """Clear scans left unfinished past the retention time, and delete their photos.

    Also deletes the photos of any finished scan that still has them. Returns how many scans were cleared.
    """
    hours = ocr_setting("RETENTION_HOURS") if hours is None else hours
    cutoff = timezone.now() - timedelta(hours=hours)
    cleared = 0
    for scan in FormScan.objects.filter(status__in=FormScan.OPEN_STATUSES, updated_at__lt=cutoff):
        scan.status = FormScan.STATUS_EXPIRED
        scan.save(update_fields=["status", "updated_at"])
        log(scan, None, "EXPIRED", hours=hours)
        purge_files(scan, reason=f"Not finished within {hours} hours")
        cleared += 1
    for scan in FormScan.objects.filter(files_deleted_at__isnull=True).exclude(status__in=FormScan.OPEN_STATUSES):
        purge_files(scan, reason="Cleaning up a finished scan")
    if cleared:
        scan_event(None, "Unfinished Scans Cleared",
                   f"{cleared} scan{'s' if cleared != 1 else ''} not finished within {hours} hours "
                   f"{'were' if cleared != 1 else 'was'} cleared and the photos deleted.")
    return cleared


@transaction.atomic
def create_scan(user, uploads, target=FormScan.TARGET_PARCEL, consent=False):
    """Store the photos privately, ask OCR, and fall back to manual entry when OCR cannot answer."""
    try:
        contents = read_uploads(uploads)
    except UploadRejected as error:
        raise ScanError(str(error)) from error
    expire_stale_scans()
    scan = FormScan(created_by=user, image_sha256=hashlib.sha256(contents[0]).hexdigest(), target=target)
    scan.image.save("scan.img", ContentFile(contents[0]), save=False)
    scan.fields = {name: "" for name in ocr_setting("FIELDS")}
    result = None
    try:
        result = ocr.extract_many(contents)
    except OcrUnavailable as error:
        scan.ocr_message = str(error)[:500]
        if isinstance(error, OcrQuotaExceeded):
            warn_admins_once("Daily Scan Limit Reached", f"The office reached its limit of {ocr_setting('DAILY_LIMIT')} scanned photos for today. Staff continue by manual entry until tomorrow.")
        elif isinstance(error, OcrAllModelsFailed):
            warn_admins_once("Form Reader Not Responding", "Every configured model failed to read a scanned form. Check the OCR provider, key and models. Staff continue by manual entry.")
    else:
        scan.ocr_available = True
        scan.ocr_provider, scan.ocr_model = result.provider, result.model
        scan.ocr_fields = {n: {"value": r.value, "confidence": r.confidence} for n, r in result.fields.items()}
        scan.fields = {n: r.value for n, r in result.fields.items()}
        scan.fields["ownership_type"] = normalize_ownership(scan.fields.get("ownership_type", ""))
        if result.unreadable_pages:
            pages = ", ".join(str(number) for number in result.unreadable_pages)
            scan.ocr_message = f"Page {pages} could not be read. Check those values by hand."
    scan.save()
    for position, raw in enumerate(contents[1:], start=2):
        page = FormScanPage(scan=scan, position=position, image_sha256=hashlib.sha256(raw).hexdigest())
        page.image.save("page.img", ContentFile(raw), save=True)
    log(scan, user, "UPLOADED", target=target, pages=len(contents), consent_confirmed=consent)
    if result:
        log(scan, user, "OCR_DONE", provider=result.provider, model=result.model, fallbacks=result.attempts,
            pages=result.pages, unreadable_pages=result.unreadable_pages)
    else:
        log(scan, user, "OCR_UNAVAILABLE", reason=scan.ocr_message)
    run_validation(scan)
    scan.save(update_fields=["traffic_light", "checks"])
    # A newer scan replaces this person's unfinished one for the same form.
    for older in FormScan.objects.filter(created_by=user, target=target, status__in=FormScan.OPEN_STATUSES).exclude(pk=scan.pk):
        discard_scan(older, user, reason="Replaced by a newer scan")
    return scan


def rejected_from(scan, accepted):
    """Groups of this scan's target that staff did not tick, given the ticked ones."""
    return [group for group in TARGET_GROUPS[scan.target] if group not in set(accepted)]


def recheck(scan, user, values, accepted=None):
    """Store edited values and accepted groups, then re-run the rules; log it when something changed."""
    changed = {k: v for k, v in values.items() if scan.fields.get(k, "") != v}
    rejected = scan.rejected_groups if accepted is None else rejected_from(scan, accepted)
    rejection_changed = sorted(rejected) != sorted(scan.rejected_groups)
    scan.fields = {**scan.fields, **values}
    scan.rejected_groups = rejected
    result = run_validation(scan)
    scan.save(update_fields=["fields", "rejected_groups", "traffic_light", "checks", "updated_at"])
    if changed or rejection_changed:
        log(scan, user, "CHECKED", changed=list(changed), rejected=rejected, status=result.status)
    return result


def commodity_value(text):
    """The official commodity name for what was written, or None."""
    lookup = {value.casefold(): value for value in ROSARIO_COMMODITY_VALUES}
    return lookup.get((text or "").strip().casefold())


def _hectares_text(text):
    hectares, _ = parse_area_hectares(text or "")
    return f"{hectares:.2f}" if hectares and hectares > 0 else ""


@transaction.atomic
def confirm_scan(scan, user, values, farmer=None, accepted=None):
    """Staff confirm the values they accepted; those are then entered in the target form, ready to save.

    A red result can never be confirmed. Rejected groups are not carried to the form.
    Nothing is written to the farm records here.
    """
    scan = FormScan.objects.select_for_update().get(pk=scan.pk)
    if scan.status not in FormScan.OPEN_STATUSES:
        raise ScanError("This scan has already been finished.")
    scan.fields = {**scan.fields, **values}
    if accepted is not None:
        scan.rejected_groups = rejected_from(scan, accepted)
    result = run_validation(scan)
    if result.blocks_approval:
        scan.save(update_fields=["fields", "rejected_groups", "traffic_light", "checks", "updated_at"])
        raise ScanError("Red checks must be corrected before this scan can be confirmed.")
    use = effective_values(scan.rejected_groups, values)
    area = _hectares_text(use.get("area_hectares"))
    if scan.target == FormScan.TARGET_PARCEL:
        barangay, _ = normalize_barangay(use.get("barangay", ""))
        if use.get("barangay") and barangay is None:
            raise ScanError("Choose a valid Rosario barangay, or untick it, before confirming.")
        if use.get("area_hectares") and not area:
            raise ScanError("Enter the farm area in hectares, or untick it, before confirming.")
        prefill = {
            "farmer": farmer.pk if farmer else "", "barangay": barangay or "", "area_hectares": area,
            "ownership_type": normalize_ownership(use.get("ownership_type", "")),
            "coordinates": format_coordinates(*result.point) if result.point else "",
        }
    else:
        commodity = commodity_value(use.get("commodity"))
        if use.get("commodity") and commodity is None:
            raise ScanError("Choose a commodity from the list, or untick it, before confirming.")
        if use.get("area_hectares") and not area:
            raise ScanError("Enter the area in hectares, or untick it, before confirming.")
        prefill = {"crop_type": commodity or "", "area_hectares": area}
    scan.prefill = prefill
    scan.farmer = farmer
    scan.status, scan.approved_by, scan.approved_at = FormScan.STATUS_CONFIRMED, user, timezone.now()
    scan.save()
    log(scan, user, "CONFIRMED", status=result.status, prefill=prefill,
        accepted=[g for g in TARGET_GROUPS[scan.target] if g not in scan.rejected_groups],
        rejected=scan.rejected_groups,
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
        rejected=scan.rejected_groups,
        ocr={n: e["value"] for n, e in scan.ocr_fields.items()}, final=final, changed=changed,
        approved_by=scan.approved_by.display_name if scan.approved_by else "")
    scan_event(
        user, "Scanned Form Saved",
        f"{user.display_name} saved a record from a scanned form (traffic light {scan.traffic_light.title()}); "
        f"{len(changed)} value{'s' if len(changed) != 1 else ''} corrected, photos deleted.",
        target_label=str(obj), path=f"/scan/{scan.pk}/",
        details=[{"field": name, "before": scan.ocr_fields.get(name, {}).get("value", ""), "after": final[name]} for name in changed],
    )
    purge_files(scan, reason="Scan saved in the record")
    return scan


def discard_scan(scan, user, reason=""):
    """End an unsaved scan: mark it discarded and delete its photos. The audit trail stays."""
    if scan.status not in FormScan.OPEN_STATUSES:
        raise ScanError("This scan has already been finished.")
    scan.status = FormScan.STATUS_DISCARDED
    scan.save(update_fields=["status", "updated_at"])
    log(scan, user, "DISCARDED", reason=reason or "Discarded by staff")
    purge_files(scan, reason=reason or "Scan discarded")
