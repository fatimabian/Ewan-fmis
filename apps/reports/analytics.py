from collections import defaultdict

from django.conf import settings
from django.core.cache import cache
from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention
from apps.service_requests.models import ServiceRequest
from .export import _filter_period, build_report, build_system_report


REPORT_METRICS_CACHE_KEY = "fmis:reports:metrics:all:v1"

ANALYTICS_TABS = (
    ("overview", "Overview"),
    ("farmers", "Farmers"),
    ("parcels", "Farm Parcels"),
    ("commodities", "Commodities"),
    ("requests", "Service Requests"),
    ("interventions", "Interventions"),
    ("reports", "Generate Reports"),
)


def _monthly_series(queryset, field_name, *, count_field="pk", value_field=None, limit=12):
    """Return compact, database-aggregated monthly counts for an analytics line."""
    aggregation = Sum(value_field) if value_field else Count(count_field, distinct=True)
    rows = list(
        queryset.annotate(period=TruncMonth(field_name))
        .values("period")
        .annotate(total=aggregation)
        .order_by("period")
    )
    rows = [row for row in rows if row["period"]][-limit:]
    peak = max((row["total"] or 0 for row in rows), default=0) or 1
    count = len(rows)
    points = []
    for index, row in enumerate(rows):
        x = 4 if count <= 1 else 4 + (index * 92 / (count - 1))
        value = row["total"] or 0
        y = 91 - (float(value) / float(peak) * 76)
        points.append(
            {
                "label": row["period"].strftime("%b %Y"),
                "value": value,
                "x": round(x, 2),
                "y": round(y, 2),
            }
        )
    return {
        "points": points,
        "polyline": " ".join(f'{point["x"]},{point["y"]}' for point in points),
        "peak": peak,
    }


def _monthly_dual_series(first_queryset, first_field, second_queryset, second_field, limit=12):
    first = {
        row["period"]: row["total"]
        for row in first_queryset.annotate(period=TruncMonth(first_field))
        .values("period")
        .annotate(total=Count("pk", distinct=True))
        .order_by("period")
        if row["period"]
    }
    second = {
        row["period"]: row["total"]
        for row in second_queryset.annotate(period=TruncMonth(second_field))
        .values("period")
        .annotate(total=Count("pk", distinct=True))
        .order_by("period")
        if row["period"]
    }
    periods = sorted(set(first) | set(second))[-limit:]
    peak = max([first.get(period, 0) for period in periods] + [second.get(period, 0) for period in periods] + [1])
    count = len(periods)
    points = []
    for index, period in enumerate(periods):
        x = 4 if count <= 1 else 4 + (index * 92 / (count - 1))
        first_value = first.get(period, 0)
        second_value = second.get(period, 0)
        points.append(
            {
                "label": period.strftime("%b %Y"),
                "first": first_value,
                "second": second_value,
                "x": round(x, 2),
                "first_y": round(91 - (first_value / peak * 76), 2),
                "second_y": round(91 - (second_value / peak * 76), 2),
            }
        )
    return {
        "points": points,
        "first_polyline": " ".join(f'{point["x"]},{point["first_y"]}' for point in points),
        "second_polyline": " ".join(f'{point["x"]},{point["second_y"]}' for point in points),
    }


def _comparison_rows(queryset, field_name, *, value_field=None, limit=5):
    annotation = Sum(value_field) if value_field else Count("pk", distinct=True)
    rows = list(
        queryset.exclude(**{field_name: ""})
        .values(field_name)
        .annotate(total=annotation)
        .order_by("-total", field_name)[:limit]
    )
    peak = max((row["total"] or 0 for row in rows), default=0) or 1
    return [
        {
            "label": row[field_name] or "Not recorded",
            "value": row["total"] or 0,
            "percent": round(float(row["total"] or 0) / float(peak) * 100),
        }
        for row in rows
    ]


def descriptive_analytics(tab="overview", date_range="all", filters=None):
    """Build privacy-safe descriptive analytics from the existing FMIS records.

    These values deliberately describe records captured by FMIS. Commodity
    records are never presented as harvest volume, and newly encoded parcel
    area is never described as physical land expansion.
    """
    filters = filters or {}
    barangay = str(filters.get("barangay", "")).strip()
    commodity = str(filters.get("commodity", "")).strip()
    request_status = str(filters.get("request_status", "")).strip()
    request_priority = str(filters.get("request_priority", "")).strip()
    intervention_type = str(filters.get("intervention_type", "")).strip()

    farmers = _filter_period(Farmer.objects.filter(is_active=True), "created_at", date_range)
    parcels = _filter_period(
        FarmParcel.objects.filter(is_active=True, farmer__is_active=True),
        "created_at",
        date_range,
    )
    crops = _filter_period(
        CropRecord.objects.filter(
            is_active=True, parcel__is_active=True, parcel__farmer__is_active=True
        ),
        "created_at",
        date_range,
    )
    requests = _filter_period(
        ServiceRequest.objects.filter(Q(farmer__is_active=True) | Q(scope="BARANGAY")),
        "created_at",
        date_range,
    )
    interventions = _filter_period(
        Intervention.objects.filter(is_active=True),
        "intervention_date",
        date_range,
        date_only=True,
    )

    if barangay:
        farmers = farmers.filter(barangay=barangay)
        parcels = parcels.filter(barangay=barangay)
        crops = crops.filter(parcel__barangay=barangay)
        requests = requests.filter(
            Q(scope="BARANGAY", target_barangay=barangay)
            | Q(scope="INDIVIDUAL", farmer__barangay=barangay)
        )
        interventions = interventions.filter(
            Q(target_barangay=barangay)
            | Q(recipients__is_active=True, recipients__farmer__barangay=barangay)
        ).distinct()
    if commodity:
        crops = crops.filter(crop_type=commodity)
    if request_status:
        requests = requests.filter(status=request_status)
    if request_priority:
        requests = requests.filter(priority=request_priority)
    if intervention_type:
        interventions = interventions.filter(intervention_type=intervention_type)

    parcel_totals = parcels.aggregate(total=Count("pk"), area=Sum("area_hectares"))
    crop_totals = crops.aggregate(
        total=Count("pk"), distinct=Count("crop_type", distinct=True), area=Sum("area_hectares")
    )
    intervention_totals = interventions.aggregate(
        total=Count("pk", distinct=True),
        farmers=Count(
            "recipients__farmer",
            filter=Q(recipients__is_active=True),
            distinct=True,
        ),
    )
    now = timezone.now()
    open_requests = requests.exclude(status__in=("COMPLETED", "CANCELLED"))
    overdue_requests = open_requests.filter(
        Q(first_responded_at__isnull=True, first_response_due_at__lt=now)
        | Q(first_responded_at__isnull=False, due_at__lt=now)
    ).distinct()
    request_status_counts = {
        row["status"]: row["total"]
        for row in requests.values("status").annotate(total=Count("pk"))
    }
    request_total = sum(request_status_counts.values())
    request_status_rows = []
    for value, label in ServiceRequest.STATUS_CHOICES:
        total = request_status_counts.get(value, 0)
        request_status_rows.append(
            {
                "label": label,
                "value": total,
                "percent": round(total / request_total * 100) if request_total else 0,
                "tone": "positive" if value == "COMPLETED" else ("danger" if value == "CANCELLED" else "neutral"),
            }
        )

    response_duration = ExpressionWrapper(
        F("first_responded_at") - F("created_at"), output_field=DurationField()
    )
    completion_duration = ExpressionWrapper(
        F("completed_at") - F("created_at"), output_field=DurationField()
    )
    timing = requests.aggregate(
        average_response=Avg(response_duration, filter=Q(first_responded_at__isnull=False)),
        average_completion=Avg(completion_duration, filter=Q(completed_at__isnull=False)),
    )

    def duration_hours(value):
        return round(value.total_seconds() / 3600, 1) if value else None

    top_commodity = (
        crops.values("crop_type").annotate(total=Count("pk")).order_by("-total", "crop_type").first()
    )
    summary = [
        {"label": "Active Farmers", "value": farmers.distinct().count(), "note": "registered in the selected period"},
        {"label": "Registered Farm Parcels", "value": parcel_totals["total"] or 0, "note": "active parcel records"},
        {"label": "Total Farm Area", "value": parcel_totals["area"] or 0, "suffix": "ha", "note": "recorded parcel area"},
        {"label": "Recorded Commodities", "value": crop_totals["distinct"] or 0, "note": f'{crop_totals["total"] or 0} active records'},
        {"label": "Service Requests Received", "value": request_total, "note": "created in the selected period"},
        {"label": "Interventions Conducted", "value": intervention_totals["total"] or 0, "note": "recorded intervention activities"},
    ]

    unpinned = parcels.filter(Q(coordinates="") | Q(coordinates__isnull=True)).count()
    findings = []
    if unpinned:
        findings.append(
            f"{unpinned} active parcel record{'s' if unpinned != 1 else ''} "
            f"{'have' if unpinned != 1 else 'has'} no saved map coordinates."
        )
    if overdue_requests.exists():
        findings.append(f"{overdue_requests.count()} open service request{'s are' if overdue_requests.count() != 1 else ' is'} overdue.")
    busiest_request_month = (
        requests.annotate(month=TruncMonth("created_at"))
        .values("month")
        .annotate(total=Count("pk"))
        .order_by("-total", "month")
        .first()
    )
    if busiest_request_month and busiest_request_month["month"]:
        findings.append(
            f'{busiest_request_month["month"].strftime("%B %Y")} recorded the highest request volume in the selected period ({busiest_request_month["total"]}).'
        )
    if not findings:
        findings.append("No overdue requests or unmapped parcel records were found for the selected filters.")

    farmer_demographics = [
        {"label": "Female", "value": farmers.filter(sex="FEMALE").count()},
        {"label": "Male", "value": farmers.filter(sex="MALE").count()},
        {"label": "4Ps", "value": farmers.filter(is_four_ps=True).count()},
        {"label": "PWD", "value": farmers.filter(is_pwd=True).count()},
        {"label": "Indigenous", "value": farmers.filter(is_indigenous=True).count()},
    ]
    reached_barangays = set(
        interventions.exclude(target_barangay="").values_list("target_barangay", flat=True)
    )
    reached_barangays.update(
        interventions.filter(recipients__is_active=True)
        .exclude(recipients__farmer__barangay="")
        .values_list("recipients__farmer__barangay", flat=True)
    )
    intervention_labels = dict(Intervention.TYPE_CHOICES)
    intervention_types = [
        {
            "label": intervention_labels.get(row["intervention_type"], row["intervention_type"]),
            "value": row["total"],
            "farmers": row["farmers"],
        }
        for row in interventions.values("intervention_type")
        .annotate(
            total=Count("pk", distinct=True),
            farmers=Count("recipients__farmer", filter=Q(recipients__is_active=True), distinct=True),
        )
        .order_by("-total", "intervention_type")[:6]
    ]

    return {
        "tab": tab,
        "summary": summary,
        "registration_series": _monthly_series(farmers, "created_at"),
        "parcel_series": _monthly_series(
            parcels, "created_at", value_field="area_hectares"
        ),
        "commodity_series": _monthly_series(crops, "created_at"),
        "request_received_series": _monthly_series(requests, "created_at"),
        "request_completed_series": _monthly_series(
            requests.filter(completed_at__isnull=False), "completed_at"
        ),
        "request_dual_series": _monthly_dual_series(
            requests,
            "created_at",
            requests.filter(completed_at__isnull=False),
            "completed_at",
        ),
        "intervention_series": _monthly_series(interventions, "intervention_date"),
        "top_farmer_barangays": _comparison_rows(farmers, "barangay"),
        "top_parcel_barangays": _comparison_rows(parcels, "barangay", value_field="area_hectares"),
        "top_commodities": _comparison_rows(crops, "crop_type", limit=7),
        "top_services": [
            {"label": row["service__name"], "value": row["total"]}
            for row in requests.values("service__name").annotate(total=Count("pk")).order_by("-total", "service__name")[:6]
        ],
        "farmer_demographics": farmer_demographics,
        "request_status_rows": request_status_rows,
        "request_total": request_total,
        "open_requests": open_requests.count(),
        "overdue_requests": overdue_requests.count(),
        "average_response_hours": duration_hours(timing["average_response"]),
        "average_completion_hours": duration_hours(timing["average_completion"]),
        "parcel_total": parcel_totals["total"] or 0,
        "parcel_area": parcel_totals["area"] or 0,
        "pinned_parcels": (parcel_totals["total"] or 0) - unpinned,
        "unpinned_parcels": unpinned,
        "crop_record_total": crop_totals["total"] or 0,
        "distinct_commodities": crop_totals["distinct"] or 0,
        "recorded_crop_area": crop_totals["area"] or 0,
        "most_recorded_commodity": top_commodity["crop_type"] if top_commodity else "No records",
        "intervention_total": intervention_totals["total"] or 0,
        "intervention_farmers": intervention_totals["farmers"] or 0,
        "intervention_types": intervention_types,
        "intervention_barangays": len(reached_barangays),
        "findings": findings[:3],
    }


def _apply_report_filters(queryset, model_name, date_range, filters):
    """Apply the same Rosario report filters to the on-screen analytics."""
    year = str(filters.get("year", "")).strip()
    barangay = str(filters.get("barangay", "")).strip()
    commodity = str(filters.get("commodity", "")).strip()
    status = str(filters.get("status", "")).strip()
    intervention_type = str(filters.get("intervention_type", "")).strip()

    if model_name == "farmer":
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(
                parcels__crops__crop_type=commodity,
                parcels__crops__is_active=True,
            ).distinct()
    elif model_name == "parcel":
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity, crops__is_active=True).distinct()
    elif model_name == "crop":
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
    elif model_name == "intervention":
        queryset = _filter_period(queryset, "intervention_date", date_range, date_only=True)
        if year:
            queryset = queryset.filter(intervention_date__year=int(year))
        if barangay:
            queryset = queryset.filter(
                recipients__is_active=True, recipients__farmer__barangay=barangay
            ).distinct()
        if commodity:
            queryset = queryset.filter(
                recipients__is_active=True,
                recipients__farmer__parcels__crops__crop_type=commodity,
                recipients__farmer__parcels__crops__is_active=True,
            ).distinct()
        if intervention_type:
            queryset = queryset.filter(intervention_type=intervention_type)
    elif model_name == "request":
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(
                Q(scope="BARANGAY", target_barangay=barangay)
                | Q(scope="INDIVIDUAL", farmer__barangay=barangay)
            )
        if commodity:
            queryset = queryset.filter(
                farmer__parcels__crops__crop_type=commodity,
                farmer__parcels__crops__is_active=True,
            ).distinct()
        if status:
            queryset = queryset.filter(status=status)
    return queryset


def report_preview(report_type, date_range, filters, system_report=False):
    """Turn the selected generated report into a readable on-screen chart and table."""
    builder = build_system_report if system_report else build_report
    if not system_report and report_type == "farmer_master":
        title, headers, rows = builder(report_type, date_range, filters, compact=True)
    else:
        title, headers, rows = builder(report_type, date_range, filters)
    chart_values = defaultdict(float)
    value_label = "Records"
    show_chart = report_type not in {"farmer_master", "service_effectiveness"}

    if report_type == "system_overview":
        for row in rows:
            chart_values[row[0]] += float(row[1] or 0)
        value_label = "Records"
    elif report_type == "user_accounts":
        for row in rows:
            chart_values[row[4] or "Not recorded"] += 1
        value_label = "Accounts"
    elif report_type == "activity_audit":
        for row in rows:
            chart_values[row[2] or "FMIS"] += 1
        value_label = "Activities"
    elif report_type == "staff_accomplishment":
        for row in rows:
            chart_values[row[0] or "Unknown staff"] += float(row[4] or 0)
        value_label = "Records handled"
    elif report_type == "farmer_master":
        # A master list is for reviewing individual farmer records. Barangay is
        # retained as a filter and a table field, not used as a substitute for
        # the farmer information itself.
        pass
    elif report_type == "commodity_per_parcel":
        for row in rows:
            chart_values[row[4] or "Not recorded"] += 1
        value_label = "Commodity records"
    elif report_type == "intervention_registry":
        for row in rows:
            chart_values[row[5] or "Not recorded"] += 1
        value_label = "Interventions"
    elif report_type == "farm_area_by_barangay":
        for row in rows:
            chart_values[row[0] or "Not recorded"] += float(row[5] or 0)
        value_label = "Hectares"
    elif report_type == "farmers_by_ownership":
        for row in rows:
            chart_values[row[0] or "Not recorded"] += float(row[6] or 0)
        value_label = "Hectares"
    elif report_type == "crop_summary":
        for row in rows:
            chart_values[row[0] or "Not recorded"] += float(row[5] or 0)
        value_label = "Hectares"
    elif report_type == "service_status":
        for row in rows:
            chart_values[row[6] or "Not recorded"] += 1
        value_label = "Requests"
    elif report_type == "service_effectiveness":
        pass
    else:
        value_indexes = {
            "intervention_summary": (1, "Interventions"),
        }
        value_index, value_label = value_indexes[report_type]
        for row in rows:
            chart_values[str(row[0] or "Not recorded")] += float(row[value_index] or 0)

    ordered = sorted(chart_values.items(), key=lambda item: (-item[1], item[0]))[:12]
    peak = max((value for _, value in ordered), default=0) or 1
    chart = []
    for label, value in ordered:
        display_value = int(value) if float(value).is_integer() else round(value, 2)
        chart.append(
            {
                "label": label,
                "value": display_value,
                "width": max(2, round(float(value) / peak * 100)) if value else 0,
            }
        )
    return {
        "title": title,
        "headers": headers,
        "rows": rows[:50],
        "total_rows": len(rows),
        "truncated": len(rows) > 50,
        "chart": chart,
        "value_label": value_label,
        "show_chart": show_chart,
        "is_farmer_master": report_type == "farmer_master",
    }


def _build_report_metrics(date_range="all", filters=None):
    filters = filters or {}
    farmers = _apply_report_filters(
        Farmer.objects.filter(is_active=True), "farmer", date_range, filters
    )
    parcels = _apply_report_filters(
        FarmParcel.objects.filter(is_active=True, farmer__is_active=True),
        "parcel",
        date_range,
        filters,
    )
    crops = _apply_report_filters(
        CropRecord.objects.filter(
            is_active=True, parcel__is_active=True, parcel__farmer__is_active=True
        ),
        "crop",
        date_range,
        filters,
    )
    requests = _apply_report_filters(
        ServiceRequest.objects.filter(
            Q(farmer__is_active=True) | Q(scope="BARANGAY")
        ),
        "request",
        date_range,
        filters,
    )
    interventions = _apply_report_filters(
        Intervention.objects.filter(
            is_active=True, recipients__is_active=True, recipients__farmer__is_active=True
        ).distinct(),
        "intervention",
        date_range,
        filters,
    )

    parcel_totals = parcels.aggregate(
        total=Count("pk", distinct=True),
        area=Sum("area_hectares"),
    )
    total_area = parcel_totals["area"] or 0
    crop_summary = list(
        crops.values("crop_type")
        .annotate(
            total=Count("id"),
            area=Sum("area_hectares"),
            farmers=Count("parcel__farmer", distinct=True),
        )
        .order_by("-area")[:6]
    )
    crop_area_total = sum((item["area"] or 0 for item in crop_summary), 0) or 1
    request_status_counts = {
        row["status"]: row["total"] for row in requests.values("status").annotate(total=Count("id"))
    }
    request_total = sum(request_status_counts.values())
    status_colors = {
        "PENDING": "#d99a12",
        "IN_PROGRESS": "#2563eb",
        "COMPLETED": "#16834f",
        "CANCELLED": "#dc4c45",
    }
    request_statuses = []
    gradient_segments = []
    cursor = 0.0
    for status, label in ServiceRequest.STATUS_CHOICES:
        total = request_status_counts.get(status, 0)
        percent = (total / request_total * 100) if request_total else 0
        color = status_colors[status]
        request_statuses.append(
            {"status": status, "label": label, "total": total, "percent": percent, "color": color}
        )
        if total:
            gradient_segments.append(f"{color} {cursor:.2f}% {cursor + percent:.2f}%")
            cursor += percent
    request_status_gradient = ", ".join(gradient_segments) or "#dfe7e2 0% 100%"

    priority_counts = {
        row["priority"]: row["total"]
        for row in requests.values("priority").annotate(total=Count("id"))
    }
    priority_colors = {"LOW": "#16834f", "MEDIUM": "#d99a12", "HIGH": "#dc4c45"}
    priority_total = sum(priority_counts.values()) or 1
    request_priorities = [
        {
            "label": label,
            "total": priority_counts.get(priority, 0),
            "percent": round(priority_counts.get(priority, 0) / priority_total * 100),
            "color": priority_colors[priority],
        }
        for priority, label in ServiceRequest.PRIORITY_CHOICES
    ]

    recent_requests = [
        {
            "farmer": req.beneficiary_label,
            "service": req.service.name,
            "label": dict(ServiceRequest.STATUS_CHOICES).get(req.status, req.status),
            "color": status_colors.get(req.status, "#61718a"),
            "date": timezone.localtime(req.created_at).strftime("%b %d, %Y"),
        }
        for req in requests.select_related("farmer", "service").order_by("-created_at")[:5]
    ]

    intervention_totals = interventions.aggregate(
        total=Count("pk", distinct=True),
        farmers=Count(
            "recipients__farmer",
            filter=Q(recipients__is_active=True),
            distinct=True,
        )
    )
    intervention_labels = dict(Intervention.TYPE_CHOICES)
    intervention_summary = [
        {
            "label": intervention_labels.get(item["intervention_type"], item["intervention_type"]),
            "total": item["total"],
            "farmers": item["farmers"],
        }
        for item in interventions.values("intervention_type")
        .annotate(
            total=Count("id", distinct=True),
            farmers=Count(
                "recipients__farmer",
                filter=Q(recipients__is_active=True),
                distinct=True,
            ),
        )
        .order_by("-total", "intervention_type")
    ]

    senior_cutoff = timezone.localdate().replace(year=timezone.localdate().year - 60)
    farmer_totals = farmers.aggregate(
        total=Count("pk", distinct=True),
        female=Count("pk", filter=Q(sex="FEMALE"), distinct=True),
        male=Count("pk", filter=Q(sex="MALE"), distinct=True),
        senior=Count("pk", filter=Q(birth_date__lte=senior_cutoff), distinct=True),
        four_ps=Count("pk", filter=Q(is_four_ps=True), distinct=True),
        pwd=Count("pk", filter=Q(is_pwd=True), distinct=True),
        indigenous=Count("pk", filter=Q(is_indigenous=True), distinct=True),
    )
    farmer_statistics = [
        {"label": "Active Farmers", "total": farmer_totals["total"]},
        {"label": "Female Farmers", "total": farmer_totals["female"]},
        {"label": "Male Farmers", "total": farmer_totals["male"]},
        {"label": "Senior Farmers", "total": farmer_totals["senior"]},
        {"label": "4Ps Beneficiaries", "total": farmer_totals["four_ps"]},
        {"label": "PWD Farmers", "total": farmer_totals["pwd"]},
        {"label": "Indigenous Farmers", "total": farmer_totals["indigenous"]},
    ]
    account_totals = CustomUser.objects.filter(deleted_at__isnull=True).aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(is_active=True)),
        admins=Count("pk", filter=Q(role="ADMIN", is_active=True)),
        staff=Count("pk", filter=Q(role="STAFF", is_active=True)),
        inactive=Count("pk", filter=Q(is_active=False)),
        pending=Count("pk", filter=Q(activation_pending=True)),
    )
    activity_totals = ActivityLog.objects.aggregate(
        total=Count("pk"),
        failed=Count("pk", filter=~Q(status__iexact="Success")),
    )
    return {
        "farmers": farmer_totals["total"],
        "parcels": parcel_totals["total"],
        "crops": crops.aggregate(total=Count("pk", distinct=True))["total"],
        "pending_requests": request_status_counts.get("PENDING", 0),
        "total_area": total_area,
        "crop_summary": crop_summary,
        "crop_area_total": crop_area_total,
        "request_statuses": request_statuses,
        "request_status_gradient": request_status_gradient,
        "request_total": request_total,
        "request_priorities": request_priorities,
        "recent_requests": recent_requests,
        "intervention_total": intervention_totals["total"],
        "intervention_farmers": intervention_totals["farmers"] or 0,
        "intervention_summary": intervention_summary,
        "activity_summary": list(
            ActivityLog.objects.values("module")
            .annotate(total=Count("id"))
            .order_by("-total")[:5]
        ),
        "farmer_statistics": farmer_statistics,
        "total_accounts": account_totals["total"],
        "active_accounts": account_totals["active"],
        "admin_accounts": account_totals["admins"],
        "staff_accounts": account_totals["staff"],
        "inactive_accounts": account_totals["inactive"],
        "pending_activations": account_totals["pending"],
        "total_activities": activity_totals["total"],
        "failed_activities": activity_totals["failed"],
    }


def report_metrics(date_range="all", filters=None):
    """Return report-dashboard metrics, caching only the unfiltered baseline.

    Filtered reports must always reflect their exact criteria. The initial
    Reports screen, however, performs the same aggregate queries for every
    visitor, so its short-lived result can safely be reused until a relevant
    model signal invalidates it.
    """
    filters = filters or {}
    is_baseline = date_range == "all" and not any(filters.values())
    timeout = settings.DASHBOARD_CACHE_SECONDS
    if not is_baseline or timeout <= 0:
        return _build_report_metrics(date_range, filters)
    cached = cache.get(REPORT_METRICS_CACHE_KEY)
    if cached is not None:
        return cached
    result = _build_report_metrics(date_range, filters)
    cache.set(REPORT_METRICS_CACHE_KEY, result, timeout)
    return result
