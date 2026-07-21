from collections import defaultdict

from django.db.models import Count, Sum
from django.utils import timezone

from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest
from .export import _filter_period, build_report


def _apply_report_filters(queryset, model_name, date_range, filters):
    """Apply the same Rosario report filters to the on-screen analytics."""
    year = str(filters.get("year", "")).strip()
    barangay = str(filters.get("barangay", "")).strip()
    commodity = str(filters.get("commodity", "")).strip()
    status = str(filters.get("status", "")).strip()

    if model_name == "farmer":
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(parcels__crops__crop_type=commodity).distinct()
    elif model_name == "parcel":
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity).distinct()
    elif model_name == "crop":
        queryset = _filter_period(queryset, "planting_date", date_range, date_only=True)
        if year:
            queryset = queryset.filter(planting_date__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
    else:
        queryset = _filter_period(queryset, "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(farmer__barangay=barangay)
        if commodity:
            queryset = queryset.filter(farmer__parcels__crops__crop_type=commodity).distinct()
        if status:
            queryset = queryset.filter(status=status)
    return queryset


def report_preview(report_type, date_range, filters):
    """Turn the selected generated report into a readable on-screen chart and table."""
    title, headers, rows = build_report(report_type, date_range, filters)
    chart_values = defaultdict(float)
    value_label = "Records"

    if report_type == "farmer_master":
        for row in rows:
            chart_values[row[2] or "Not recorded"] += 1
        value_label = "Farmers"
    elif report_type == "commodity_per_parcel":
        for row in rows:
            chart_values[row[4] or "Not recorded"] += 1
        value_label = "Crop records"
    else:
        value_indexes = {
            "farmers_by_barangay": (1, "Farmers"),
            "farm_area_by_barangay": (2, "Hectares"),
            "farmers_by_ownership": (3, "Hectares"),
            "crop_summary": (3, "Hectares"),
            "service_status": (1, "Requests"),
        }
        value_index, value_label = value_indexes[report_type]
        for row in rows:
            chart_values[str(row[0] or "Not recorded")] += float(row[value_index] or 0)

    ordered = sorted(chart_values.items(), key=lambda item: (-item[1], item[0]))[:12]
    peak = max((value for _, value in ordered), default=0) or 1
    chart = []
    for label, value in ordered:
        display_value = int(value) if float(value).is_integer() else round(value, 2)
        chart.append({
            "label": label,
            "value": display_value,
            "width": max(2, round(float(value) / peak * 100)) if value else 0,
        })
    return {
        "title": title,
        "headers": headers,
        "rows": rows[:50],
        "total_rows": len(rows),
        "truncated": len(rows) > 50,
        "chart": chart,
        "value_label": value_label,
    }


def report_metrics(date_range="all", filters=None):
    filters = filters or {}
    farmers = _apply_report_filters(Farmer.objects.filter(is_active=True), "farmer", date_range, filters)
    parcels = _apply_report_filters(
        FarmParcel.objects.filter(is_active=True, farmer__is_active=True), "parcel", date_range, filters
    )
    crops = _apply_report_filters(
        CropRecord.objects.filter(parcel__is_active=True, parcel__farmer__is_active=True), "crop", date_range, filters
    )
    requests = _apply_report_filters(
        ServiceRequest.objects.filter(farmer__is_active=True), "request", date_range, filters
    )

    total_area = parcels.aggregate(total=Sum("area_hectares"))["total"] or 0
    crop_summary = list(
        crops.values("crop_type")
        .annotate(total=Count("id"), area=Sum("area_hectares"), farmers=Count("parcel__farmer", distinct=True))
        .order_by("-area")[:6]
    )
    crop_area_total = sum((item["area"] or 0 for item in crop_summary), 0) or 1
    request_status_counts = {
        row["status"]: row["total"] for row in requests.values("status").annotate(total=Count("id"))
    }
    request_total = sum(request_status_counts.values())
    status_colors = {
        "PENDING": "#d99a12", "IN_PROGRESS": "#2563eb",
        "COMPLETED": "#16834f", "CANCELLED": "#dc4c45",
    }
    request_statuses = []
    gradient_segments = []
    cursor = 0.0
    for status, label in ServiceRequest.STATUS_CHOICES:
        total = request_status_counts.get(status, 0)
        percent = (total / request_total * 100) if request_total else 0
        color = status_colors[status]
        request_statuses.append({"status": status, "label": label, "total": total, "percent": percent, "color": color})
        if total:
            gradient_segments.append(f"{color} {cursor:.2f}% {cursor + percent:.2f}%")
            cursor += percent
    request_status_gradient = ", ".join(gradient_segments) or "#dfe7e2 0% 100%"

    priority_counts = {
        row["priority"]: row["total"] for row in requests.values("priority").annotate(total=Count("id"))
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
        "farmers": farmers.count(), "parcels": parcels.count(), "crops": crops.count(),
        "pending_requests": requests.filter(status="PENDING").count(), "total_area": total_area,
        "crop_summary": crop_summary, "crop_area_total": crop_area_total,
        "request_statuses": request_statuses, "request_status_gradient": request_status_gradient,
        "request_total": request_total,
        "request_priorities": request_priorities, "recent_requests": recent_requests,
        "activity_summary": ActivityLog.objects.values("module").annotate(total=Count("id")).order_by("-total")[:5],
        "farmer_statistics": farmer_statistics,
        "service_count": ServiceCatalog.objects.filter(is_active=True).count(),
        "total_accounts": CustomUser.objects.count(),
        "active_accounts": CustomUser.objects.filter(is_active=True).count(),
        "admin_accounts": CustomUser.objects.filter(role="ADMIN", is_active=True).count(),
        "staff_accounts": CustomUser.objects.filter(role="STAFF", is_active=True).count(),
        "inactive_accounts": CustomUser.objects.filter(is_active=False).count(),
        "inactive_catalogs": ServiceCatalog.objects.filter(is_active=False).count(),
        "total_activities": ActivityLog.objects.count(),
    }
