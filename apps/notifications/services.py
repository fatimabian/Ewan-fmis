import logging

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.urls import reverse

from .models import Notification


logger = logging.getLogger(__name__)

STAFF_MODULES = {"Farmers", "Farm Parcels", "Crops", "Service Requests"}
ADMIN_MODULES = {"User Accounts"}


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

    actor_name = activity.actor.display_name if activity.actor else "The system"
    if activity.target_label:
        message = f"{activity.target_label}'s record was updated by {actor_name}."
    else:
        message = f"{actor_name} completed an update in {activity.module}."
    secure_url = f'{reverse("activity_logs:list")}?highlight={activity.pk}#activity-{activity.pk}'

    notifications = [
        Notification(
            recipient=recipient,
            source_activity=activity,
            title=activity.title or "System update",
            message=message,
            category=category,
            url=secure_url,
        )
        for recipient in recipients.distinct()
    ]
    if not notifications:
        return 0
    Notification.objects.bulk_create(notifications, ignore_conflicts=True)
    return len(notifications)
