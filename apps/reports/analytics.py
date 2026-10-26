from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention
from apps.service_requests.models import ServiceRequest
from .export import _filter_period, build_report, build_system_report


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
    show_chart = report_type != "farmer_master"

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


def report_metrics(date_range="all", filters=None):
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
        "activity_summary": ActivityLog.objects.values("module")
        .annotate(total=Count("id"))
        .order_by("-total")[:5],
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
