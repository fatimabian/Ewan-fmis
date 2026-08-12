from datetime import timedelta
import logging

from django.db.models import Max
from django.utils import timezone

from .models import ActivityLog


logger = logging.getLogger(__name__)


def _friendly_activity(method, path):
    labels = [
        (
            "/catalog/",
            "Service Catalog",
            "Service Catalogs",
            "added or updated an agricultural service in the catalog.",
        ),
        ("/farmers/", "Farmer Record", "Farmers", "added or updated a farmer record."),
        ("/parcels/", "Farm Parcel", "Farm Parcels", "added or updated a farm parcel record."),
        ("/crops/", "Crop Record", "Crops", "added or updated a crop record."),
        (
            "/requests/",
            "Service Request",
            "Service Requests",
            "created or updated a farmer service request.",
        ),
        ("/accounts/", "User Account", "User Accounts", "created or updated a user account."),
        (
            "/settings/",
            "Account Settings",
            "Settings",
            "updated account preferences and notification settings.",
        ),
    ]
    for fragment, subject, module, phrase in labels:
        if fragment in path:
            lowered_path = path.lower()
            if any(part in lowered_path for part in ("delete", "archive")):
                verb = "Archived"
            elif any(part in lowered_path for part in ("add", "new", "create")):
                verb = "Created"
            else:
                verb = "Updated"
            return f"{subject} {verb}", module, phrase
    return (
        "System Record Updated",
        "FMIS",
        "updated a record in the Farmer Management Information System.",
    )


def _recent_farmer_audit(user, path):
    if not any(fragment in path for fragment in ("/farmers/", "/parcels/", "/crops/")):
        return {}

    from apps.farmers.models import FarmerUpdateHistory

    last_audit_time = ActivityLog.objects.filter(
        actor=user,
        module__in=("Farmers", "Farm Parcels", "Crops"),
    ).aggregate(latest=Max("created_at"))["latest"]
    filters = {
        "actor": user,
        "created_at__gte": timezone.now() - timedelta(seconds=45),
    }
    if last_audit_time is not None:
        filters["created_at__gt"] = last_audit_time

    history = (
        FarmerUpdateHistory.objects.select_related("farmer")
        .filter(**filters)
        .order_by("-created_at", "-pk")
        .first()
    )
    if history is None:
        return {}

    reason = history.get_change_reason_display()
    if history.remarks:
        reason = f"{reason} - {history.remarks}"
    return {
        "target_label": history.farmer.full_name,
        "reason": reason,
        "details": history.changes,
    }


def log_activity(user, action, path):
    title, module, phrase = _friendly_activity(action.split()[0], path)
    actor_name = user.display_name if user.is_authenticated else "A user"
    audit = _recent_farmer_audit(user, path)
    values = {
        "actor": user if user.is_authenticated else None,
        "action": action,
        "path": path,
        "title": title,
        "module": module,
        "description": f"{actor_name} {phrase}",
        "target_label": audit.get("target_label", ""),
        "reason": audit.get("reason", ""),
        "details": audit.get("details", []),
    }
    try:
        activity = ActivityLog.objects.create(**values)
    except TypeError as error:
        if "unexpected keyword arguments" not in str(error):
            raise
        logger.warning(
            "ActivityLog model was stale; writing a basic compatible activity entry.",
            exc_info=True,
        )
        for optional_field in ("target_label", "reason", "details"):
            values.pop(optional_field, None)
        activity = ActivityLog.objects.create(**values)
    try:
        from apps.notifications.services import create_activity_notifications

        create_activity_notifications(activity)
    except Exception:
        logger.exception("In-app notification creation failed for activity %s.", activity.pk)
    return activity
