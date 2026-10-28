from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
from apps.service_requests.models import ServiceRequest
from apps.settings_page.models import BackupRun

from .services import ADMIN_DASHBOARD_CACHE_KEY, STAFF_DASHBOARD_CACHE_KEY


REPORT_METRICS_CACHE_KEY = "fmis:reports:metrics:all:v1"


@receiver(
    (post_save, post_delete),
    sender=ActivityLog,
    dispatch_uid="dashboard_activity_changed",
)
@receiver(
    (post_save, post_delete),
    sender=CustomUser,
    dispatch_uid="dashboard_account_changed",
)
@receiver(
    (post_save, post_delete),
    sender=BackupRun,
    dispatch_uid="dashboard_backup_changed",
)
def clear_admin_dashboard_cache(**kwargs):
    cache.delete(ADMIN_DASHBOARD_CACHE_KEY)
    cache.delete(REPORT_METRICS_CACHE_KEY)


def _clear_staff_cache(**kwargs):
    cache.delete(STAFF_DASHBOARD_CACHE_KEY)
    cache.delete(REPORT_METRICS_CACHE_KEY)


for model in (
    Farmer,
    FarmParcel,
    CropRecord,
    ServiceRequest,
    Intervention,
    InterventionRecipient,
):
    post_save.connect(
        _clear_staff_cache,
        sender=model,
        weak=False,
        dispatch_uid=f"staff_dashboard_{model._meta.label_lower}_saved",
    )
    post_delete.connect(
        _clear_staff_cache,
        sender=model,
        weak=False,
        dispatch_uid=f"staff_dashboard_{model._meta.label_lower}_deleted",
    )
