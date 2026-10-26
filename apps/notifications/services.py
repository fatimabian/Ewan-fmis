import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse

from .models import Notification


logger = logging.getLogger(__name__)

STAFF_MODULES = {
    "Farmers",
    "Farm Parcels",
    "Crops",
    "Service Requests",
    "Interventions",
}
ADMIN_MODULES = {"User Accounts"}

STAFF_MODULE_ROUTES = {
    "Farmers": "farmers:list",
    "Farm Parcels": "farm_parcels:list",
    "Crops": "crops:list",
    "Service Requests": "service_requests:list",
    "Interventions": "interventions:list",
}

RECORD_LABELS = {
    "Farmers": "farmer record",
    "Farm Parcels": "farm parcel",
    "Crops": "commodity record",
    "Service Requests": "service request",
    "Interventions": "intervention",
    "User Accounts": "user account",
}


def _actor_name(activity):
    return activity.actor.display_name if activity.actor else "The system"


def _notification_copy(activity):
    """Translate audit details into short, non-technical notification text."""
    title = (activity.title or "").casefold()
    actor_name = _actor_name(activity)

    if activity.module == "Security" or activity.status.casefold() != "success":
        if "access denied" in title:
            return (
                "Restricted page blocked",
                f"{actor_name} tried to open a page that is not available for their account. No changes were made.",
            )
        if "sign-in blocked" in title:
            return (
                "Sign-in temporarily blocked",
                "Several incorrect sign-in attempts were blocked. No account access was granted.",
            )
        if "failed sign-in" in title:
            return (
                "Unsuccessful sign-in",
                "Someone entered incorrect sign-in details. No account access was granted.",
            )
        return (
            "Action needs attention",
            activity.description or "An action could not be completed. Open the activity page for more information.",
        )

    record_label = RECORD_LABELS.get(activity.module, "record")
    if "created" in title:
        verb = "created"
    elif "set inactive" in title:
        verb = "set inactive"
    elif "reactivated" in title:
        verb = "reactivated"
    elif "archived" in title:
        verb = "set inactive"
    elif "restored" in title:
        verb = "reactivated"
    else:
        verb = "updated"

    target = (activity.target_label or "").strip()
    if target and not target.startswith("/"):
        message = f"{actor_name} {verb} the {record_label} for {target}."
    else:
        message = f"{actor_name} {verb} a {record_label}."
    return activity.title or f"{record_label.title()} updated", message


def _activity_target(activity, user):
    if user.is_admin:
        return (
            f'{reverse("activity_logs:list")}?highlight={activity.pk}'
            f"#activity-{activity.pk}"
        )
    route_name = STAFF_MODULE_ROUTES.get(activity.module)
    if route_name and activity.status.casefold() == "success":
        return reverse(route_name)
    return reverse("notifications:list")


def notification_target(notification, user):
    """Return a destination that the notification recipient's role may open."""
    activity = notification.source_activity
    if activity is None:
        return notification.url or reverse("notifications:list")
    return _activity_target(activity, user)


def create_activity_notifications(activity):
    """Create privacy-safe notices for meaningful, successful audited changes."""
    if activity.status.casefold() != "success":
        role_filter = Q(role="ADMIN") | Q(is_superuser=True)
        category = "warning"
    elif activity.module in STAFF_MODULES:
        role_filter = Q(role="STAFF")
        category = "records"
    elif activity.module in ADMIN_MODULES:
        role_filter = Q(role="ADMIN") | Q(is_superuser=True)
        category = "accounts"
    else:
        return 0

    preference_filter = Q(preferences__in_app_notifications=True) | Q(preferences__isnull=True)
    recipients = get_user_model().objects.filter(
        role_filter,
        preference_filter,
        is_active=True,
    )
    if activity.actor_id:
        recipients = recipients.exclude(pk=activity.actor_id)

    title, message = _notification_copy(activity)
    notifications = [
        Notification(
            recipient=recipient,
            source_activity=activity,
            title=title,
            message=message[:255],
            category=category,
            url=_activity_target(activity, recipient),
        )
        for recipient in recipients.distinct()
    ]
    if not notifications:
        return 0
    Notification.objects.bulk_create(notifications, ignore_conflicts=True)
    return len(notifications)
