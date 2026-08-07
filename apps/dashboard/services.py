from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q, Sum
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
        activity_trend.append(
            {
                "label": day.strftime("%a"),
                "total": ActivityLog.objects.filter(
                    created_at__gte=_day_boundary(day),
                    created_at__lt=_day_boundary(day + timedelta(days=1)),
                ).count(),
            }
        )
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


def _crop_recommendation(today, crop_rows):
    """Return transparent seasonal decision support, never a field-level prescription."""
    is_wet_season = 6 <= today.month <= 11
    season = "Wet season" if is_wet_season else "Dry season"
    preferred_terms = (
        ("rice", "palay", "banana", "vegetable")
        if is_wet_season
        else ("corn", "maize", "cassava", "mung", "peanut", "vegetable")
    )
    compatible = [
        row
        for row in crop_rows
        if any(term in row["crop_type"].lower() for term in preferred_terms)
    ]
    selected = (
        compatible[0]
        if compatible
        else {"crop_type": "Rice" if is_wet_season else "Corn", "area": 0}
    )
    evidence = (
        f"{selected['area']:.2f} ha recorded locally"
        if selected.get("area")
        else "seasonal baseline; no local crop area is recorded yet"
    )
    return {
        "season": season,
        "crop": selected["crop_type"],
        "evidence": evidence,
        "note": (
            "Use this as planning support only. Confirm the parcel's soil, drainage, water "
            "access, seed availability, and current agricultural advisories before planting."
        ),
    }


def staff_dashboard_metrics():
    """Rosario-only operational and crop-planning summary for staff."""
    today = timezone.localdate()
    current_month = _month_start(today)
    requests = ServiceRequest.objects.select_related("farmer", "service")
    open_filter = Q(status="PENDING") | Q(status="IN_PROGRESS")
    rosario_parcels = FarmParcel.objects.filter(
        is_active=True,
        municipality__iexact="Rosario",
        province__iexact="Batangas",
    )
    rosario_crops = CropRecord.objects.filter(parcel__in=rosario_parcels)
    crop_rows = list(
        rosario_crops.values("crop_type")
        .annotate(area=Sum("area_hectares"), records=Count("id"))
        .order_by("-area", "crop_type")[:5]
    )
    crop_peak = max((float(row["area"] or 0) for row in crop_rows), default=0)
    for index, row in enumerate(crop_rows):
        row["area"] = float(row["area"] or 0)
        row["height"] = max(8, round((row["area"] / crop_peak) * 100)) if crop_peak else 8
        row["is_largest"] = index == 0

    status_counts = {
        "pending": requests.filter(status="PENDING").count(),
        "in_progress": requests.filter(status="IN_PROGRESS").count(),
        "completed": requests.filter(status="COMPLETED").count(),
    }
    total_area = rosario_crops.aggregate(total=Sum("area_hectares"))["total"] or 0

    return {
        "farmers": Farmer.objects.filter(
            is_active=True,
            city_municipality__iexact="Rosario",
            province__iexact="Batangas",
        ).count(),
        "parcels": rosario_parcels.count(),
        "crops": rosario_crops.count(),
        "area_planted": total_area,
        "open_requests": requests.filter(open_filter).count(),
        "urgent_requests": requests.filter(open_filter, priority="HIGH").count(),
        "completed_this_month": requests.filter(
            status="COMPLETED", updated_at__gte=_day_boundary(current_month)
        ).count(),
        "request_status": status_counts,
        "crop_chart": crop_rows,
        "crop_chart_total": sum(row["records"] for row in crop_rows),
        "crop_recommendation": _crop_recommendation(today, crop_rows),
        "recent_requests": requests.filter(open_filter)[:5],
        "dashboard_date": today,
    }
