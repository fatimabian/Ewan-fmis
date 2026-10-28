from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.activity_logs.services import record_event
from .models import (
    FarmParcel,
    ParcelCoordinateHistory,
    ParcelCoordinateReview,
)


def format_coordinates(latitude, longitude):
    return f"{latitude:.7f}, {longitude:.7f}"


def parse_coordinates(value):
    """Return a WGS84 latitude/longitude pair without estimating a location."""
    try:
        parts = [part.strip() for part in str(value or "").split(",")]
        if len(parts) != 2:
            return None
        latitude, longitude = (float(part) for part in parts)
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def validate_coordinate_for_barangay(*, barangay, latitude, longitude):
    """Validate a WGS84 point without restricting it to a barangay polygon.

    The public function name is retained for form and review compatibility. The
    map save endpoint separately enforces Rosario's municipal boundary.
    """
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValidationError("Enter coordinates as latitude, longitude.")
    return latitude, longitude


def validate_coordinate_text_for_barangay(*, barangay, coordinates):
    point = parse_coordinates(coordinates)
    if point is None:
        raise ValidationError("Enter coordinates as latitude, longitude.")
    return validate_coordinate_for_barangay(
        barangay=barangay,
        latitude=point[0],
        longitude=point[1],
    )


def clear_coordinate_caches(parcel):
    cache.delete_many(
        [
            "farm-parcel-pin-counts:all",
            f"farm-parcel-pin-counts:{parcel.barangay}",
        ]
    )


@transaction.atomic
def propose_coordinate_change(
    *, parcel, actor, operation, proposed_coordinates="", issue_codes=None,
    evidence_source="Staff map selection", evidence_reference="", notes=""
):
    locked = FarmParcel.objects.select_for_update().get(pk=parcel.pk)
    if operation == ParcelCoordinateReview.OPERATION_SET:
        validate_coordinate_text_for_barangay(
            barangay=locked.barangay,
            coordinates=proposed_coordinates,
        )
    ParcelCoordinateReview.objects.filter(
        parcel=locked, status=ParcelCoordinateReview.STATUS_PENDING
    ).update(
        status=ParcelCoordinateReview.STATUS_REJECTED,
        reviewed_by=actor,
        reviewed_at=timezone.now(),
        decision_notes="Superseded by a newer coordinate proposal.",
    )
    review = ParcelCoordinateReview.objects.create(
        parcel=locked,
        operation=operation,
        original_coordinates=(locked.coordinates or "").strip(),
        proposed_coordinates=(proposed_coordinates or "").strip(),
        issue_codes=issue_codes or [],
        evidence_source=evidence_source,
        evidence_reference=evidence_reference,
        staff_notes=notes,
        submitted_by=actor,
    )
    clear_coordinate_caches(locked)
    return review


@transaction.atomic
def approve_coordinate_review(*, review_id, actor, decision_notes=""):
    review = (
        ParcelCoordinateReview.objects.select_for_update()
        .select_related("parcel")
        .get(pk=review_id)
    )
    if review.status != ParcelCoordinateReview.STATUS_PENDING:
        raise ValidationError("This coordinate proposal has already been reviewed.")
    parcel = FarmParcel.objects.select_for_update().get(pk=review.parcel_id)
    current = (parcel.coordinates or "").strip()
    if current != review.original_coordinates:
        raise ValidationError(
            "The parcel coordinates changed after this proposal was submitted. "
            "Reject it and create a new proposal from the current record."
        )
    after = "" if review.operation == ParcelCoordinateReview.OPERATION_REMOVE else review.proposed_coordinates
    if after:
        validate_coordinate_text_for_barangay(
            barangay=parcel.barangay,
            coordinates=after,
        )
    parcel.coordinates = after
    update_fields = ["coordinates"]
    if parcel.remarks.startswith("FMIS-DEMO-DATA:") and after:
        parcel.remarks = parcel.remarks.replace("FMIS-DEMO-DATA:", "FMIS-DEMO-VERIFIED:", 1)
        update_fields.append("remarks")
    parcel.save(update_fields=update_fields)
    review.status = ParcelCoordinateReview.STATUS_APPROVED
    review.reviewed_by = actor
    review.reviewed_at = timezone.now()
    review.decision_notes = decision_notes
    review.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_notes"])
    history = ParcelCoordinateHistory.objects.create(
        parcel=parcel,
        review=review,
        action=ParcelCoordinateHistory.ACTION_APPROVED,
        before_coordinates=current,
        after_coordinates=after,
        reason=decision_notes or review.staff_notes or "Approved coordinate verification.",
        changed_by=actor,
    )
    clear_coordinate_caches(parcel)
    record_event(
        actor=actor,
        title="Farm Parcel Coordinate Approved",
        module="Farm Parcels",
        description=f"{actor.display_name} approved a reviewed farm parcel coordinate change.",
        path=f"/parcels/map/verification/{review.pk}/approve/",
        target_label=parcel.display_name,
        reason=history.reason,
        details=[{"field": "Farm parcel coordinates", "before": current or "Not pinned", "after": after or "Not pinned"}],
    )
    return review, history


@transaction.atomic
def reject_coordinate_review(*, review_id, actor, decision_notes=""):
    review = ParcelCoordinateReview.objects.select_for_update().get(pk=review_id)
    if review.status != ParcelCoordinateReview.STATUS_PENDING:
        raise ValidationError("This coordinate proposal has already been reviewed.")
    review.status = ParcelCoordinateReview.STATUS_REJECTED
    review.reviewed_by = actor
    review.reviewed_at = timezone.now()
    review.decision_notes = decision_notes or "Coordinate proposal rejected during verification."
    review.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_notes"])
    return review


@transaction.atomic
def reverse_coordinate_history(*, history_id, actor, reason):
    history = (
        ParcelCoordinateHistory.objects.select_for_update()
        .select_related("parcel", "review")
        .get(pk=history_id)
    )
    if history.action != ParcelCoordinateHistory.ACTION_APPROVED or hasattr(history, "reversal_entry"):
        raise ValidationError("This coordinate change cannot be reversed again.")
    parcel = FarmParcel.objects.select_for_update().get(pk=history.parcel_id)
    current = (parcel.coordinates or "").strip()
    if current != history.after_coordinates:
        raise ValidationError(
            "The parcel has a newer coordinate value. Review the newer history before reversing."
        )
    parcel.coordinates = history.before_coordinates
    parcel.save(update_fields=["coordinates"])
    reversal = ParcelCoordinateHistory.objects.create(
        parcel=parcel,
        review=history.review,
        action=ParcelCoordinateHistory.ACTION_REVERSED,
        before_coordinates=current,
        after_coordinates=history.before_coordinates,
        reason=reason,
        changed_by=actor,
        reversed_history=history,
    )
    history.review.status = ParcelCoordinateReview.STATUS_REVERSED
    history.review.save(update_fields=["status"])
    clear_coordinate_caches(parcel)
    record_event(
        actor=actor,
        title="Farm Parcel Coordinate Reversed",
        module="Farm Parcels",
        description=f"{actor.display_name} reversed an approved coordinate change.",
        path=f"/parcels/map/verification/history/{history.pk}/reverse/",
        target_label=parcel.display_name,
        reason=reason,
        details=[{"field": "Farm parcel coordinates", "before": current or "Not pinned", "after": history.before_coordinates or "Not pinned"}],
    )
    return reversal
