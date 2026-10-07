from collections import defaultdict

from django.db.models import Count, Sum
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
        queryset = _filter_period(queryset, "planting_date", date_range, date_only=True)
        if year:
            queryset = queryset.filter(planting_date__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
    elif model_name == "intervention":
        queryset = _filter_period(queryset, "intervention_date", date_range, date_only=True)
        if year:
            queryset = queryset.filter(intervention_date__year=int(year))
        if barangay:
            queryset = queryset.filter(farmer__barangay=barangay)
        if commodity:
            queryset = queryset.filter(
                farmer__parcels__crops__crop_type=commodity,
                farmer__parcels__crops__is_active=True,
            ).distinct()
        if intervention_type:
            queryset = queryset.filter(intervention_type=intervention_type)
    else:
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(farmer__barangay=barangay)
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
    elif report_type == "farmer_master":
        # A master list is for reviewing individual farmer records. Barangay is
        # retained as a filter and a table field, not used as a substitute for
        # the farmer information itself.
        pass
    elif report_type == "commodity_per_parcel":
        for row in rows:
            chart_values[row[4] or "Not recorded"] += 1
        value_label = "Crop records"
    elif report_type == "intervention_registry":
        for row in rows:
            chart_values[row[5] or "Not recorded"] += 1
        value_label = "Interventions"
    elif report_type == "farmers_by_barangay":
        for row in rows:
            chart_values[row[0] or "Not recorded"] += 1
        value_label = "Farmers"
    elif report_type == "farm_area_by_barangay":
        for row in rows:
            chart_values[row[0] or "Not recorded"] += float(row[4] or 0)
        value_label = "Hectares"
    elif report_type == "farmers_by_ownership":
        for row in rows:
            chart_values[row[0] or "Not recorded"] += float(row[5] or 0)
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
    preview_headers = headers
    preview_rows = rows
    if report_type == "farmer_master":
        preview_headers = [
            "Farmer ID",
            "Farmer Name",
            "RSBSA ID",
            "Registration Status",
            "Barangay",
            "Phone",
            "Livelihood",
            "Farm Records",
        ]
        preview_rows = [
            [
                row[0],
                row[8],
                row[2],
                row[3],
                row[15],
                row[20],
                row[32],
                f"{row[47]} parcel(s) · {row[50]} crop(s)",
            ]
            for row in rows
        ]

    return {
        "title": title,
        "headers": preview_headers,
        "rows": preview_rows[:50],
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
        ServiceRequest.objects.filter(farmer__is_active=True), "request", date_range, filters
    )
    interventions = _apply_report_filters(
        Intervention.objects.filter(is_active=True, farmer__is_active=True),
        "intervention",
        date_range,
        filters,
    )

    total_area = parcels.aggregate(total=Sum("area_hectares"))["total"] or 0
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
            "farmer": req.farmer.full_name,
            "service": req.service.name,
            "label": dict(ServiceRequest.STATUS_CHOICES).get(req.status, req.status),
            "color": status_colors.get(req.status, "#61718a"),
            "date": timezone.localtime(req.created_at).strftime("%b %d, %Y"),
        }
        for req in requests.select_related("farmer", "service").order_by("-created_at")[:5]
    ]

    intervention_totals = interventions.aggregate(farmers=Count("farmer", distinct=True))
    intervention_labels = dict(Intervention.TYPE_CHOICES)
    intervention_summary = [
        {
            "label": intervention_labels.get(item["intervention_type"], item["intervention_type"]),
            "total": item["total"],
            "farmers": item["farmers"],
        }
        for item in interventions.values("intervention_type")
        .annotate(
            total=Count("id"),
            farmers=Count("farmer", distinct=True),
        )
        .order_by("-total", "intervention_type")
    ]

    senior_cutoff = timezone.localdate().replace(year=timezone.localdate().year - 60)
    farmer_statistics = [
        {"label": "Active Farmers", "total": farmers.count()},
        {"label": "Female Farmers", "total": farmers.filter(sex="FEMALE").count()},
        {"label": "Male Farmers", "total": farmers.filter(sex="MALE").count()},
        {"label": "Senior Farmers", "total": farmers.filter(birth_date__lte=senior_cutoff).count()},
        {"label": "4Ps Beneficiaries", "total": farmers.filter(is_four_ps=True).count()},
        {"label": "PWD Farmers", "total": farmers.filter(is_pwd=True).count()},
        {"label": "Indigenous Farmers", "total": farmers.filter(is_indigenous=True).count()},
    ]
    return {
        "farmers": farmers.count(),
        "parcels": parcels.count(),
        "crops": crops.count(),
        "pending_requests": requests.filter(status="PENDING").count(),
        "total_area": total_area,
        "crop_summary": crop_summary,
        "crop_area_total": crop_area_total,
        "request_statuses": request_statuses,
        "request_status_gradient": request_status_gradient,
        "request_total": request_total,
        "request_priorities": request_priorities,
        "recent_requests": recent_requests,
        "intervention_total": interventions.count(),
        "intervention_farmers": intervention_totals["farmers"] or 0,
        "intervention_summary": intervention_summary,
        "activity_summary": ActivityLog.objects.values("module")
        .annotate(total=Count("id"))
        .order_by("-total")[:5],
        "farmer_statistics": farmer_statistics,
        "total_accounts": CustomUser.objects.count(),
        "active_accounts": CustomUser.objects.filter(is_active=True).count(),
        "admin_accounts": CustomUser.objects.filter(role="ADMIN", is_active=True).count(),
        "staff_accounts": CustomUser.objects.filter(role="STAFF", is_active=True).count(),
        "inactive_accounts": CustomUser.objects.filter(is_active=False).count(),
        "pending_activations": CustomUser.objects.filter(activation_pending=True).count(),
        "total_activities": ActivityLog.objects.count(),
        "failed_activities": ActivityLog.objects.exclude(status__iexact="Success").count(),
    }
