from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import FarmerUpdateHistory


def _json_value(value):
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def farmer_snapshot(farmer):
    """Return a readable, JSON-safe snapshot of the farmer and farm records."""
    snapshot = {}
    excluded_farmer_fields = {
        "photo",
        "created_at",
        "last_updated_by",
        "last_updated_at",
    }
    for field in farmer._meta.concrete_fields:
        if field.name in excluded_farmer_fields or field.is_relation:
            continue
        label = f"Personal / {str(field.verbose_name).title()}"
        display = getattr(farmer, f"get_{field.name}_display", None)
        value = display() if callable(display) else getattr(farmer, field.name)
        snapshot[label] = _json_value(value)

    for parcel_number, parcel in enumerate(
        farmer.parcels.all().order_by("pk").prefetch_related("crops"),
        start=1,
    ):
        parcel_prefix = f"Parcel {parcel_number}"
        for field in parcel._meta.concrete_fields:
            if field.name in {"farmer", "created_at"} or field.is_relation:
                continue
            display = getattr(parcel, f"get_{field.name}_display", None)
            value = display() if callable(display) else getattr(parcel, field.name)
            snapshot[f"{parcel_prefix} / {str(field.verbose_name).title()}"] = _json_value(value)
        for crop_number, crop in enumerate(parcel.crops.all().order_by("pk"), start=1):
            crop_prefix = f"{parcel_prefix} / Commodity {crop_number}"
            for field in crop._meta.concrete_fields:
                if field.name in {"parcel", "image"} or field.is_relation:
                    continue
                snapshot[f"{crop_prefix} / {str(field.verbose_name).title()}"] = _json_value(
                    getattr(crop, field.name)
                )
    return snapshot


def compare_snapshots(before, after):
    changes = []
    for field in sorted(set(before) | set(after)):
        old_value = before.get(field, "")
        new_value = after.get(field, "")
        if old_value != new_value:
            changes.append(
                {
                    "field": field,
                    "before": old_value or "Not recorded",
                    "after": new_value or "Not recorded",
                }
            )
    return changes


@transaction.atomic
def record_farmer_update(
    *,
    farmer,
    actor,
    update_type,
    before,
    transaction_code="",
    change_reason="CORRECTION",
    remarks="",
    date_signed=None,
    date_received=None,
    agriculturist_name="",
):
    farmer.refresh_from_db()
    after = farmer_snapshot(farmer)
    history = FarmerUpdateHistory.objects.create(
        farmer=farmer,
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        update_type=update_type,
        transaction_code=transaction_code,
        change_reason=change_reason or "CORRECTION",
        remarks=remarks,
        date_signed=date_signed,
        date_received=date_received,
        agriculturist_name=agriculturist_name,
        snapshot_before=before,
        snapshot_after=after,
        changes=compare_snapshots(before, after),
    )
    farmer.last_updated_by = history.actor
    farmer.last_updated_at = timezone.now()
    farmer.save(update_fields=["last_updated_by", "last_updated_at"])
    return history
