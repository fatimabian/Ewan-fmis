from datetime import date, datetime, time, timedelta
from math import ceil, floor, log10

from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, CharField, Count, Max, Q, Sum, Value, When
from django.utils import timezone

from apps.common.constants import COMMODITY_DETAIL_TO_GROUP
from apps.common.crop_symbols import crop_symbol

from apps.crops.models import CropRecord
from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention
from apps.service_requests.models import ServiceRequest
from apps.service_requests.services import service_effectiveness_metrics
from apps.settings_page.models import BackupRun
from decimal import Decimal


ADMIN_DASHBOARD_CACHE_KEY = "fmis:dashboard:admin:v1"
STAFF_DASHBOARD_CACHE_KEY = "fmis:dashboard:staff:v1"

# A restrained, agriculture-inspired palette keeps the commodity chart readable
# without the harsh rainbow effect produced by evenly-spaced HSL hues.  The
# final soft green is reserved for the aggregated "Others" slice.
COMMODITY_CHART_COLORS = (
    "#239B68",  # emerald
    "#2F9DB5",  # teal blue
    "#5B7FC5",  # cornflower
    "#8B6FC0",  # violet
    "#E0A63A",  # harvest gold
    "#D76A5B",  # coral
    "#6EAA45",  # leaf green
    "#3C8FC1",  # sky blue
    "#C88B2E",  # amber
    "#C15C82",  # berry
)
COMMODITY_OTHERS_COLOR = "#6F9B83"


def _cached_dashboard(key, builder):
    timeout = settings.DASHBOARD_CACHE_SECONDS
    if timeout <= 0:
        return builder()
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = builder()
    cache.set(key, result, timeout)
    return result


def _day_boundary(value):
    """Return a timezone-aware local midnight without relying on DB timezone tables."""
    return timezone.make_aware(datetime.combine(value, time.min), timezone.get_current_timezone())


def _farmer_chart_scale(peak):
    """Return a readable scale that keeps small datasets visually meaningful."""
    if peak <= 4:
        ceiling = max(peak, 1)
        step = 1
        return ceiling, list(range(ceiling, -1, -step))
    else:
        rough_step = peak / 4
        magnitude = 10 ** floor(log10(rough_step))
        normalized = rough_step / magnitude
        nice_factor = next(value for value in (1, 2, 5, 10) if normalized <= value)
        step = int(nice_factor * magnitude)
    ceiling = step * ceil(peak / step)
    return ceiling, list(range(ceiling, -1, -step))


def _build_dashboard_metrics():
    today = timezone.localdate()
    first_day = today - timedelta(days=6)
    day_ranges = []
    for offset in range(7):
        day = first_day + timedelta(days=offset)
        day_ranges.append(
            {
                "date": day,
                "label": day.strftime("%a"),
            }
        )
    activity_summary = ActivityLog.objects.aggregate(
        **{
            f"day_{offset}": Count(
                "pk",
                filter=Q(
                    created_at__gte=_day_boundary(item["date"]),
                    created_at__lt=_day_boundary(item["date"] + timedelta(days=1)),
                ),
            )
            for offset, item in enumerate(day_ranges)
        },
        failed_events=Count(
            "pk",
            filter=(
                Q(module="Security", created_at__gte=_day_boundary(first_day))
                & ~Q(status__iexact="Success")
            ),
        ),
    )
    activity_trend = [
        {**item, "total": activity_summary[f"day_{offset}"]}
        for offset, item in enumerate(day_ranges)
    ]
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
    account_summary = CustomUser.objects.filter(deleted_at__isnull=True).aggregate(
        accounts=Count("pk"),
        active_accounts=Count("pk", filter=Q(is_active=True)),
        admins=Count("pk", filter=Q(role="ADMIN", is_active=True)),
        staff=Count("pk", filter=Q(role="STAFF", is_active=True)),
        pending_activations=Count("pk", filter=Q(activation_pending=True)),
        inactive_accounts=Count("pk", filter=Q(is_active=False)),
    )
    latest_backup = BackupRun.objects.first()
    return {
        **account_summary,
        "service_effectiveness": service_effectiveness_metrics(),
        "events_today": activity_summary["day_6"],
        "failed_events": (
            activity_summary["failed_events"]
            + BackupRun.objects.filter(
                status="FAILED",
                started_at__gte=_day_boundary(first_day),
            ).count()
        ),
        "activity_trend": activity_trend,
        "activity_line_points": activity_line_points,
        "activity_area_points": (
            f"{chart_left},{chart_bottom} {activity_line_points} "
            f"{chart_right},{chart_bottom}"
        ),
        "activity_week_total": sum(item["total"] for item in activity_trend),
        "recent_activity": list(ActivityLog.objects.select_related("actor")[:6]),
        "latest_backup": latest_backup,
        "backup_scheduler_configured": settings.FMIS_BACKUP_SCHEDULER_CONFIGURED,
        "backup_encryption_configured": bool(settings.FMIS_BACKUP_ENCRYPTION_KEY),
        "backup_offsite_configured": bool(
            settings.BACKUP_AZURE_CONTAINER_URL or settings.BACKUP_RCLONE_REMOTE
        ),
    }


def dashboard_metrics():
    return _cached_dashboard(ADMIN_DASHBOARD_CACHE_KEY, _build_dashboard_metrics)


def _month_start(value):
    return date(value.year, value.month, 1)


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
            f"{selected['records']} commodity record(s) · {selected['area']:.2f} ha · "
            f"{coverage}% recognized labels"
        )
        reason = (
            f"{selected['crop']} leads after comparing seasonal fit with Rosario's "
            "recorded area, frequency, and planting recency."
        )
    else:
        evidence = "No recognized Rosario commodity records yet · seasonal baseline only"
        reason = (
            f"{selected['crop']} leads only on the {season.lower()} baseline. "
            "Add validated commodity records before treating this as local evidence."
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
        "source": "Seasonal baseline plus active Rosario commodity records; live weather is shown separately.",
        "note": (
            "Seasonal reference only—not a planting instruction. Validate soil, drainage, "
            "water access, seed availability, and current DA/PAGASA advisories first."
        ),
    }


def _build_staff_dashboard_metrics():
    """Rosario-only operational and crop-planning summary for staff."""
    today = timezone.localdate()
    current_month = _month_start(today)
    requests = ServiceRequest.objects.select_related("farmer", "service")
    open_filter = Q(status="PENDING") | Q(status="IN_PROGRESS")
    # FMIS is already scoped to Rosario at the application and form level.
    # Query the live operational tables directly here. Re-filtering on free-text
    # location fields caused otherwise valid saved records (for example legacy
    # values with trailing spaces) to disappear from every dashboard metric.
    rosario_farmers = Farmer.objects.filter(is_active=True)
    # Summary cards reflect every saved parcel belonging to an active farmer.
    # Operational attention checks remain limited to active parcels, while the
    # commodity mix follows the commodity record's own active/inactive status.
    # This keeps the dashboard consistent with the parcel and commodity lists
    # when a saved parcel is inactive but its commodity record is still active.
    rosario_parcels = FarmParcel.objects.filter(farmer__is_active=True)
    active_rosario_parcels = rosario_parcels.filter(is_active=True)
    rosario_crops = CropRecord.objects.filter(
        is_active=True,
        parcel__farmer__is_active=True,
    )
    recommendation_rows = list(
        rosario_crops.values("crop_type")
        .annotate(
            area=Sum("area_hectares"),
            records=Count("id"),
            farmers=Count("parcel__farmer", distinct=True),
            latest_planting=Max("planting_date"),
        )
        .order_by("-farmers", "-area", "crop_type")
    )
    commodity_group_case = Case(
        *[
            When(crop_type__iexact=detail, then=Value(group))
            for detail, group in COMMODITY_DETAIL_TO_GROUP.items()
        ],
        default=Value("Other Commodity"),
        output_field=CharField(),
    )
    grouped_rosario_crops = rosario_crops.annotate(
        commodity_group=commodity_group_case
    )
    commodity_group_rows = list(
        grouped_rosario_crops
        .values("commodity_group")
        .annotate(
            records=Count("id"),
            farmers=Count("parcel__farmer", distinct=True),
        )
        .order_by("-records", "commodity_group")
    )
    farmer_totals = rosario_farmers.aggregate(
        total=Count("pk"),
        incomplete=Count("pk", filter=~Q(registration_status="COMPLETED")),
    )
    parcel_totals = rosario_parcels.aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(is_active=True)),
        unmapped=Count(
            "pk",
            filter=Q(is_active=True) & (Q(coordinates="") | Q(coordinates__isnull=True)),
        ),
        managed_area=Sum("area_hectares"),
    )
    attention_chart = [
        {
            "key": "registration",
            "label": "Registrations to complete",
            "help": "Active farmer records not yet marked completed",
            "count": farmer_totals["incomplete"],
        },
        {
            "key": "parcel",
            "label": "Farmers without parcels",
            "help": "Active farmers with no active farm parcel",
            "count": rosario_farmers.annotate(
                active_parcels=Count(
                    "parcels", filter=Q(parcels__is_active=True)
                )
            ).filter(active_parcels=0).count(),
        },
        {
            "key": "mapping",
            "label": "Parcels without map pins",
            "help": "Active parcels without saved coordinates",
            "count": parcel_totals["unmapped"],
        },
        {
            "key": "crop",
            "label": "Parcels without commodities",
            "help": "Active parcels with no active commodity record",
            "count": active_rosario_parcels.annotate(
                active_crops=Count("crops", filter=Q(crops__is_active=True))
            ).filter(active_crops=0).count(),
        },
    ]
    attention_peak = max((item["count"] for item in attention_chart), default=0)
    for item in attention_chart:
        item["width"] = (
            max(3, round((item["count"] / attention_peak) * 100))
            if item["count"] and attention_peak
            else 0
        )

    attention_priority = max(attention_chart, key=lambda item: item["count"])

    sorted_commodity_rows = sorted(
        commodity_group_rows,
        key=lambda row: (-int(row["records"] or 0), row["commodity_group"] or ""),
    )
    total_crops = sum(int(row["records"] or 0) for row in sorted_commodity_rows)
    top_commodity_rows = sorted_commodity_rows[:10]
    remaining_commodity_rows = sorted_commodity_rows[10:]
    if remaining_commodity_rows:
        remaining_labels = [row["commodity_group"] for row in remaining_commodity_rows]
        top_commodity_rows.append(
            {
                "commodity_group": "Others",
                "records": sum(int(row["records"] or 0) for row in remaining_commodity_rows),
                "farmers": grouped_rosario_crops.filter(
                    commodity_group__in=remaining_labels
                )
                .values("parcel__farmer_id")
                .distinct()
                .count(),
            }
        )
    commodity_breakdown = [
        {
            "label": row["commodity_group"] or "Other Commodity",
            "records": int(row["records"] or 0),
            "farmers": (
                int(row["farmers"] or 0)
                if row.get("farmers") is not None
                else None
            ),
        }
        for row in top_commodity_rows
    ]
    commodity_offset = 0.0
    for index, item in enumerate(commodity_breakdown):
        share = round((item["records"] / total_crops) * 100, 2) if total_crops else 0
        is_others = item["label"] == "Others"
        item.update(
            {
                "color": (
                    COMMODITY_OTHERS_COLOR
                    if is_others
                    else COMMODITY_CHART_COLORS[index % len(COMMODITY_CHART_COLORS)]
                ),
                "share": share,
                "remainder": round(100 - share, 2),
                "offset": round(commodity_offset, 2),
            }
        )
        commodity_offset += share

    total_farmers = farmer_totals["total"]
    barangay_distribution = list(
        rosario_farmers.values("barangay")
        .annotate(total=Count("pk"))
        .order_by("-total", "barangay")
    )
    for index, item in enumerate(barangay_distribution, start=1):
        item["rank"] = index
        item["share"] = (
            round((item["total"] / total_farmers) * 100) if total_farmers else 0
        )

    rosario_requests = requests.filter(farmer__in=rosario_farmers)
    most_requested_services = list(
        rosario_requests
        .values("service__name")
        .annotate(total=Count("pk"))
        .order_by("-total", "service__name")[:3]
    )

    request_summary = rosario_requests.aggregate(
        pending=Count("pk", filter=Q(status="PENDING")),
        in_progress=Count("pk", filter=Q(status="IN_PROGRESS")),
        completed=Count("pk", filter=Q(status="COMPLETED")),
        open_requests=Count("pk", filter=open_filter),
        urgent_requests=Count("pk", filter=open_filter & Q(priority="HIGH")),
        completed_this_month=Count(
            "pk",
            filter=Q(status="COMPLETED", updated_at__gte=_day_boundary(current_month)),
        ),
    )
    intervention_summary = Intervention.objects.filter(
        is_active=True,
        recipients__is_active=True,
        recipients__farmer__in=rosario_farmers,
    ).aggregate(
        total=Count("pk", distinct=True),
        farmers=Count("recipients__farmer", distinct=True),
        scheduled=Count("pk", filter=Q(status="SCHEDULED"), distinct=True),
        ongoing=Count("pk", filter=Q(status="ONGOING"), distinct=True),
        completed=Count("pk", filter=Q(status="COMPLETED"), distinct=True),
    )
    status_counts = {
        "pending": request_summary["pending"],
        "in_progress": request_summary["in_progress"],
        "completed": request_summary["completed"],
    }
    total_area = sum(
        (Decimal(str(row["area"] or 0)) for row in recommendation_rows),
        Decimal("0"),
    )
    total_parcels = parcel_totals["total"]
    managed_land_area = parcel_totals["managed_area"] or Decimal("0")
    registration_complete = total_farmers - attention_chart[0]["count"]
    active_parcel_count = parcel_totals["active"]
    mapped_parcels = active_parcel_count - attention_chart[2]["count"]
    parcels_with_commodities = active_parcel_count - attention_chart[3]["count"]
    completeness_denominator = total_farmers + (active_parcel_count * 2)
    completeness_total = registration_complete + mapped_parcels + parcels_with_commodities
    data_completeness_score = (
        round((completeness_total / completeness_denominator) * 100)
        if completeness_denominator
        else 0
    )
    return {
        "farmers": total_farmers,
        "parcels": total_parcels,
        "crops": total_crops,
        "area_planted": total_area,
        "managed_land_area": managed_land_area,
        "open_requests": request_summary["open_requests"],
        "urgent_requests": request_summary["urgent_requests"],
        "completed_this_month": request_summary["completed_this_month"],
        "intervention_total": intervention_summary["total"] or 0,
        "intervention_farmers": intervention_summary["farmers"] or 0,
        "request_status": status_counts,
        "attention_chart": attention_chart,
        "attention_total": sum(item["count"] for item in attention_chart),
        "attention_priority": attention_priority,
        "commodity_breakdown": commodity_breakdown,
        "barangay_distribution": barangay_distribution,
        "most_requested_services": most_requested_services,
        "data_completeness_score": data_completeness_score,
        "intervention_status": {
            "scheduled": intervention_summary["scheduled"] or 0,
            "ongoing": intervention_summary["ongoing"] or 0,
            "completed": intervention_summary["completed"] or 0,
        },
        "crop_recommendation": _crop_recommendation(today, recommendation_rows),
        "recent_requests": list(rosario_requests.filter(open_filter)[:5]),
        "dashboard_date": today,
        "service_effectiveness": service_effectiveness_metrics(rosario_requests),
    }


def staff_dashboard_metrics():
    return _cached_dashboard(STAFF_DASHBOARD_CACHE_KEY, _build_staff_dashboard_metrics)
