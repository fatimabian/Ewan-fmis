from datetime import date, datetime, time, timedelta

from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from apps.common.crop_symbols import crop_symbol

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
                "date": day,
                "label": day.strftime("%a"),
                "total": ActivityLog.objects.filter(
                    created_at__gte=_day_boundary(day),
                    created_at__lt=_day_boundary(day + timedelta(days=1)),
                ).count(),
            }
        )
    peak = max((item["total"] for item in activity_trend), default=0)
    chart_left = 45
    chart_right = 655
    chart_top = 25
    chart_bottom = 170
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top
    for index, item in enumerate(activity_trend):
        item["height"] = max(8, round((item["total"] / peak) * 100)) if peak else 8
        item["chart_x"] = round(chart_left + (chart_width * index / 6), 2)
        item["chart_y"] = round(
            chart_bottom - ((item["total"] / peak) * chart_height),
            2,
        ) if peak else chart_bottom
        item["chart_value_y"] = max(12, round(item["chart_y"] - 13, 2))
    activity_line_points = " ".join(
        f'{item["chart_x"]},{item["chart_y"]}' for item in activity_trend
    )
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
        "activity_line_points": activity_line_points,
        "activity_area_points": (
            f"{chart_left},{chart_bottom} {activity_line_points} "
            f"{chart_right},{chart_bottom}"
        ),
        "activity_week_total": sum(item["total"] for item in activity_trend),
        "recent_activity": ActivityLog.objects.select_related("actor")[:6],
    }


def _month_start(value):
    return date(value.year, value.month, 1)


def _shift_month(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _canonical_crop_name(value):
    """Match common local crop labels without treating unknown entries as evidence."""
    normalized = (value or "").strip().lower()
    aliases = {
        "Rice": ("rice", "palay"),
        "Corn": ("corn", "maize"),
        "Mung Bean": ("mung bean", "mungbean", "mongo", "monggo"),
        "Peanut": ("peanut", "mani"),
        "Cassava": ("cassava", "kamoteng kahoy"),
        "Sweet Potato": ("sweet potato", "kamote"),
        "Banana": ("banana", "saging"),
        "Coconut": ("coconut", "niyog"),
        "Tomato": ("tomato", "kamatis"),
        "Eggplant": ("eggplant", "talong"),
        "Vegetables": ("vegetable", "gulay"),
    }
    for crop, terms in aliases.items():
        if any(term in normalized for term in terms):
            return crop
    return None


def _crop_recommendation(today, crop_rows):
    """Build an explainable municipal baseline, never a parcel-level prescription."""
    is_wet_season = 6 <= today.month <= 11
    season = "Wet season" if is_wet_season else "Dry season"
    season_window = "June-November" if is_wet_season else "December-May"
    seasonal_fit = (
        {
            "Rice": 1.00,
            "Banana": 0.80,
            "Coconut": 0.75,
            "Vegetables": 0.65,
            "Cassava": 0.55,
        }
        if is_wet_season
        else {
            "Corn": 1.00,
            "Mung Bean": 0.90,
            "Peanut": 0.85,
            "Cassava": 0.80,
            "Sweet Potato": 0.75,
            "Tomato": 0.70,
            "Eggplant": 0.65,
        }
    )

    local = {}
    total_database_records = 0
    for row in crop_rows:
        records = int(row.get("records") or 0)
        total_database_records += records
        crop = _canonical_crop_name(row.get("crop_type"))
        if not crop:
            continue
        entry = local.setdefault(
            crop,
            {"area": 0.0, "records": 0, "latest_planting": None},
        )
        entry["area"] += float(row.get("area") or 0)
        entry["records"] += records
        latest = row.get("latest_planting")
        if latest and (not entry["latest_planting"] or latest > entry["latest_planting"]):
            entry["latest_planting"] = latest

    candidate_local = {crop: local.get(crop, {}) for crop in seasonal_fit}
    max_area = max((item.get("area", 0) for item in candidate_local.values()), default=0)
    max_records = max(
        (item.get("records", 0) for item in candidate_local.values()),
        default=0,
    )

    candidates = []
    for crop, fit in seasonal_fit.items():
        evidence = candidate_local[crop]
        area = float(evidence.get("area", 0))
        records = int(evidence.get("records", 0))
        latest = evidence.get("latest_planting")
        data_strength = min(1, records / 20)
        recency = 0
        if latest:
            age = (today - latest).days
            recency = 1 if age <= 365 else 0.5 if age <= 730 else 0
        score = (
            (fit * 0.50)
            + ((area / max_area if max_area else 0) * 0.25 * data_strength)
            + ((records / max_records if max_records else 0) * 0.15 * data_strength)
            + (recency * 0.10 * data_strength)
        )
        candidates.append(
            {
                "crop": crop,
                "score": round(score * 100),
                "area": area,
                "records": records,
            }
        )

    selected = max(candidates, key=lambda item: item["score"])
    recognized_records = sum(item["records"] for item in candidates)
    coverage = (
        round((recognized_records / total_database_records) * 100)
        if total_database_records
        else 0
    )
    if selected["records"] >= 20 and selected["area"] >= 10 and coverage >= 75:
        confidence = "High"
    elif selected["records"] >= 5 and selected["area"] > 0 and coverage >= 50:
        confidence = "Moderate"
    else:
        confidence = "Low"

    if recognized_records:
        evidence = (
            f"{selected['crop']}: {selected['records']} record(s) · "
            f"{selected['area']:.2f} ha · sample {min(selected['records'], 20)}/20 · "
            f"{coverage}% recognized-label coverage"
        )
        reason = (
            f"{selected['crop']} ranked highest after comparing the season baseline "
            "with Rosario's recorded area, frequency, and planting recency."
        )
    else:
        evidence = "No recognized Rosario crop records yet · seasonal baseline only"
        reason = (
            f"{selected['crop']} leads only on the {season.lower()} baseline. "
            "Add validated crop records before treating this as local evidence."
        )

    return {
        "season": season,
        "season_window": season_window,
        "crop": selected["crop"],
        "symbol": crop_symbol(selected["crop"]),
        "score": selected["score"],
        "confidence": confidence,
        "confidence_class": confidence.lower(),
        "evidence": evidence,
        "reason": reason,
        "methodology": (
            "50% season · up to 25% area · 15% records · 10% recency; "
            "local weight grows with sample size"
        ),
        "source": "PAGASA national season window + recorded Rosario crop data",
        "note": (
            "Planning support only—not a planting instruction. Validate soil, drainage, "
            "water access, seed availability, and current DA/PAGASA advisories first."
        ),
    }


def staff_dashboard_metrics():
    """Rosario-only operational and crop-planning summary for staff."""
    today = timezone.localdate()
    current_month = _month_start(today)
    requests = ServiceRequest.objects.select_related("farmer", "service")
    open_filter = Q(status="PENDING") | Q(status="IN_PROGRESS")
    rosario_farmers = Farmer.objects.filter(
        is_active=True,
        city_municipality__iexact="Rosario",
        province__iexact="Batangas",
    )
    rosario_parcels = FarmParcel.objects.filter(
        is_active=True,
        municipality__iexact="Rosario",
        province__iexact="Batangas",
    )
    rosario_crops = CropRecord.objects.filter(parcel__in=rosario_parcels)
    recommendation_rows = list(
        rosario_crops.values("crop_type")
        .annotate(
            area=Sum("area_hectares"),
            records=Count("id"),
            latest_planting=Max("planting_date"),
        )
        .order_by("-area", "crop_type")
    )
    crop_rows = recommendation_rows[:5]
    crop_peak = max((float(row["area"] or 0) for row in crop_rows), default=0)
    for index, row in enumerate(crop_rows):
        row["area"] = float(row["area"] or 0)
        row["symbol"] = crop_symbol(row["crop_type"])
        row["height"] = max(8, round((row["area"] / crop_peak) * 100)) if crop_peak else 8
        row["is_largest"] = index == 0

    status_counts = {
        "pending": requests.filter(status="PENDING").count(),
        "in_progress": requests.filter(status="IN_PROGRESS").count(),
        "completed": requests.filter(status="COMPLETED").count(),
    }
    total_area = rosario_crops.aggregate(total=Sum("area_hectares"))["total"] or 0
    total_farmers = rosario_farmers.count()

    service_rows = list(
        requests.values("service__name", "service__icon_name")
        .annotate(total=Count("id"))
        .order_by("-total", "service__name")
    )
    service_request_total = sum(row["total"] for row in service_rows)
    service_colors = ["#16a34a", "#2563eb", "#f59e0b", "#7c3aed", "#e85d3f", "#0891b2"]
    service_chart = []
    chart_cursor = 0.0
    chart_segments = []
    for index, row in enumerate(service_rows):
        percentage = (row["total"] / service_request_total * 100) if service_request_total else 0
        color = service_colors[index % len(service_colors)]
        chart_segments.append(f"{color} {chart_cursor:.2f}% {chart_cursor + percentage:.2f}%")
        service_chart.append(
            {
                "name": row["service__name"],
                "icon": row["service__icon_name"] or "bi-journal-text",
                "total": row["total"],
                "percentage": round(percentage),
                "color": color,
                "is_largest": index == 0,
            }
        )
        chart_cursor += percentage

    return {
        "farmers": total_farmers,
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
        "crop_recommendation": _crop_recommendation(today, recommendation_rows),
        "recent_requests": requests.filter(open_filter)[:5],
        "service_request_chart": service_chart,
        "service_request_total": service_request_total,
        "service_request_gradient": (
            f"conic-gradient({', '.join(chart_segments)})"
            if chart_segments
            else "conic-gradient(#dfe7e2 0 100%)"
        ),
        "dashboard_date": today,
    }
