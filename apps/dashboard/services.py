from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.crops.models import CropRecord
from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest
from apps.service_catalog.models import ServiceCatalog


def _day_boundary(value):
    """Return a timezone-aware local midnight without relying on DB timezone tables."""
    return timezone.make_aware(datetime.combine(value, time.min), timezone.get_current_timezone())


def dashboard_metrics():
    today = timezone.localdate()
    first_day = today - timedelta(days=6)
    activity_trend = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        activity_trend.append({
            "label": day.strftime("%a"),
            "total": ActivityLog.objects.filter(
                created_at__gte=_day_boundary(day),
                created_at__lt=_day_boundary(day + timedelta(days=1)),
            ).count(),
        })
    peak = max((item["total"] for item in activity_trend), default=0)
    for item in activity_trend:
        item["height"] = max(8, round((item["total"] / peak) * 100)) if peak else 8
    return {
        "accounts": CustomUser.objects.count(),
        "active_accounts": CustomUser.objects.filter(is_active=True).count(),
        "admins": CustomUser.objects.filter(role="ADMIN", is_active=True).count(),
        "staff": CustomUser.objects.filter(role="STAFF", is_active=True).count(),
        "service_catalogs": ServiceCatalog.objects.filter(is_active=True).count(),
        "draft_catalogs": ServiceCatalog.objects.filter(is_active=False).count(),
        "events_today": ActivityLog.objects.filter(
            created_at__gte=_day_boundary(today),
            created_at__lt=_day_boundary(today + timedelta(days=1)),
        ).count(),
        "failed_events": ActivityLog.objects.exclude(status__iexact="Success").count(),
        "activity_trend": activity_trend,
        "activity_week_total": sum(item["total"] for item in activity_trend),
        "recent_activity": ActivityLog.objects.select_related("actor")[:6],
    }


def _month_start(value):
    return date(value.year, value.month, 1)


def _shift_month(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def staff_dashboard_metrics():
    """Operational summary for staff, based only on records they manage."""
    today = timezone.localdate()
    current_month = _month_start(today)
    first_month = _shift_month(current_month, -5)
    requests = ServiceRequest.objects.select_related("farmer", "service")

    request_trend = []
    for offset in range(6):
        month = _shift_month(first_month, offset)
        next_month = _shift_month(month, 1)
        total = requests.filter(
            created_at__gte=_day_boundary(month), created_at__lt=_day_boundary(next_month)
        ).count()
        request_trend.append({"label": month.strftime("%b"), "total": total})

    peak = max((item["total"] for item in request_trend), default=0)
    for item in request_trend:
        item["height"] = max(8, round((item["total"] / peak) * 100)) if peak else 8

    open_filter = Q(status="PENDING") | Q(status="IN_PROGRESS")
    status_counts = {
        "pending": requests.filter(status="PENDING").count(),
        "in_progress": requests.filter(status="IN_PROGRESS").count(),
        "completed": requests.filter(status="COMPLETED").count(),
    }

    return {
        "farmers": Farmer.objects.filter(is_active=True).count(),
        "parcels": FarmParcel.objects.filter(is_active=True).count(),
        "crops": CropRecord.objects.count(),
        "open_requests": requests.filter(open_filter).count(),
        "urgent_requests": requests.filter(open_filter, priority="HIGH").count(),
        "completed_this_month": requests.filter(
            status="COMPLETED", updated_at__gte=_day_boundary(current_month)
        ).count(),
        "request_status": status_counts,
        "request_trend": request_trend,
        "request_six_month_total": sum(item["total"] for item in request_trend),
        "recent_requests": requests.filter(open_filter)[:5],
    }
