"""Audit log entries and admin warnings for the scan cycle.

Success events go to the Activity Log only (no notification: staff do not need an alert for every scan).
Warnings reach administrators through the normal notification system, at most once a day each.
"""
import logging

from django.utils import timezone

from apps.activity_logs.models import ActivityLog
from apps.activity_logs.services import record_event, record_request_event

logger = logging.getLogger(__name__)

MODULE = "Scan & Auto-Fill"
TARGET_LABELS = {"PARCEL": "Farm Parcel form", "CROP": "Commodity form", "FARMER": "Farmer Registration form"}


def scan_event(actor, title, description, *, request=None, target_label="", path="/scan/", details=None, status="Success"):
    """Write one audit entry; never lets a logging problem break the scan itself.

    With a request, the generic "record updated" entry the middleware would add is suppressed,
    so each step appears once and with the right meaning.
    """
    values = dict(actor=actor, title=title, module=MODULE, description=description[:255],
                  path=path, target_label=target_label, details=details or [], status=status)
    try:
        if request is not None:
            return record_request_event(request, **{**values, "path": path})
        return record_event(**values)
    except Exception:
        logger.exception("Could not write the scan audit entry %r.", title)
        return None


def quiet_request(request):
    """Mark a request as handled so the middleware does not log it as a record change."""
    request._fmis_activity_recorded = True


def warn_admins_once(title, description):
    """Raise an administrator warning, but only once per day for the same problem."""
    already = ActivityLog.objects.filter(module=MODULE, title=title, created_at__date=timezone.localdate()).exists()
    if already:
        return None
    return scan_event(None, title, description, status="Warning")
