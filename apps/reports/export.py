import csv
import re
from calendar import monthrange

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone

from apps.crops.models import CropRecord
from apps.common.constants import ROSARIO_BARANGAYS
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest


REPORT_TEMPLATES = [
    {"key": "farmer_master", "title": "Farmer Master List", "description": "Active farmer IDs, contact details, barangay, and RSBSA numbers", "icon": "bi-people"},
    {"key": "farmers_by_barangay", "title": "Total Farmers per Barangay", "description": "Registered farmers grouped by Rosario barangay", "icon": "bi-geo-alt"},
    {"key": "farm_area_by_barangay", "title": "Total Farm Area per Barangay", "description": "Farm parcels and consolidated hectares grouped by barangay", "icon": "bi-map"},
    {"key": "farmers_by_ownership", "title": "Farmers by Land Ownership", "description": "Farmers, parcels, and area grouped by ownership or tenure", "icon": "bi-house-check"},
    {"key": "crop_summary", "title": "Crop Production Summary", "description": "Farmer count, crop records, and planted area by crop", "icon": "bi-flower1"},
    {"key": "commodity_per_parcel", "title": "Commodity per Farm Parcel", "description": "Each active parcel with its farmer and recorded commodities", "icon": "bi-grid-3x3-gap"},
    {"key": "service_status", "title": "Service Request Status", "description": "Farmer service requests grouped by current status", "icon": "bi-clipboard-check"},
]
REPORT_KEYS = {item["key"] for item in REPORT_TEMPLATES}
DATE_RANGES = {"all": "All Records", "3": "Last 3 Months", "6": "Last 6 Months", "12": "Last 12 Months"}
FORMATS = {"csv", "pdf"}
FILTER_LABELS = {"year": "Year", "barangay": "Barangay", "commodity": "Commodity", "status": "Request Status"}


def _cutoff(months):
    if months == "all":
        return None
    now = timezone.now()
    month_index = now.year * 12 + now.month - 1 - int(months)
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return now.replace(year=year, month=month, day=min(now.day, monthrange(year, month)[1]))


def _filter_period(queryset, field_name, months, date_only=False):
    cutoff = _cutoff(months)
    if cutoff is None:
        return queryset
    value = cutoff.date() if date_only else cutoff
    return queryset.filter(**{f"{field_name}__gte": value})


def build_report(report_type, date_range, filters=None):
    if report_type not in REPORT_KEYS or date_range not in DATE_RANGES:
        raise ValueError("Choose a valid report template and date range.")
    filters = filters or {}
    year = str(filters.get("year", "")).strip()
    barangay = str(filters.get("barangay", "")).strip()
    commodity = str(filters.get("commodity", "")).strip()
    status = str(filters.get("status", "")).strip()
    if year and (not year.isdigit() or len(year) != 4):
        raise ValueError("Choose a valid report year.")
    if barangay and barangay not in ROSARIO_BARANGAYS:
        raise ValueError("Choose a valid Rosario barangay.")
    if commodity and len(commodity) > 100:
        raise ValueError("Choose a valid commodity.")
    if status and status not in dict(ServiceRequest.STATUS_CHOICES):
        raise ValueError("Choose a valid request status.")

    if report_type == "farmer_master":
        queryset = _filter_period(Farmer.objects.filter(is_active=True).prefetch_related("parcels__crops"), "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(parcels__crops__crop_type=commodity).distinct()
        rows = [
            [farmer.record_id, farmer.full_name, farmer.barangay, farmer.primary_commodity, farmer.phone_number or "-", farmer.rsbsa_number or "-", farmer.remarks or "-"]
            for farmer in queryset.order_by("last_name", "first_name")
        ]
        return "Farmer Master List", ["Farmer ID", "Farmer Name", "Barangay", "Primary Commodity", "Phone", "RSBSA Number", "Remarks"], rows

    if report_type == "farmers_by_barangay":
        queryset = _filter_period(Farmer.objects.filter(is_active=True), "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(parcels__crops__crop_type=commodity).distinct()
        data = queryset.values("barangay").annotate(total=Count("id")).order_by("barangay")
        return "Total Farmers per Barangay", ["Barangay", "Registered Farmers"], [[item["barangay"], item["total"]] for item in data]

    if report_type == "farm_area_by_barangay":
        queryset = _filter_period(FarmParcel.objects.filter(is_active=True, farmer__is_active=True), "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity).distinct()
        data = queryset.values("barangay").annotate(parcels=Count("id"), area=Sum("area_hectares")).order_by("barangay")
        return "Total Farm Area per Barangay", ["Barangay", "Farm Parcels", "Total Area (ha)"], [[item["barangay"], item["parcels"], item["area"] or 0] for item in data]

    if report_type == "farmers_by_ownership":
        queryset = _filter_period(FarmParcel.objects.filter(is_active=True, farmer__is_active=True), "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity).distinct()
        data = queryset.values("ownership_type").annotate(farmers=Count("farmer", distinct=True), parcels=Count("id"), area=Sum("area_hectares")).order_by("ownership_type")
        labels = dict(FarmParcel.OWNERSHIP_CHOICES)
        return "Farmers by Land Ownership", ["Ownership / Tenure", "Farmers", "Parcels", "Area (ha)"], [[labels.get(item["ownership_type"], item["ownership_type"]), item["farmers"], item["parcels"], item["area"] or 0] for item in data]

    if report_type == "crop_summary":
        queryset = _filter_period(CropRecord.objects.filter(parcel__is_active=True, parcel__farmer__is_active=True), "planting_date", date_range, date_only=True)
        if year:
            queryset = queryset.filter(planting_date__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
        data = queryset.values("crop_type").annotate(farmers=Count("parcel__farmer", distinct=True), records=Count("id"), area=Sum("area_hectares")).order_by("crop_type")
        return "Crop Production Summary", ["Crop / Commodity", "Farmers", "Crop Records", "Planted Area (ha)"], [[item["crop_type"], item["farmers"], item["records"], item["area"] or 0] for item in data]

    if report_type == "commodity_per_parcel":
        queryset = _filter_period(
            CropRecord.objects.filter(parcel__is_active=True, parcel__farmer__is_active=True).select_related("parcel__farmer"),
            "planting_date", date_range, date_only=True,
        )
        if year:
            queryset = queryset.filter(planting_date__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
        rows = [[
            crop.parcel.farmer.record_id, crop.parcel.farmer.full_name, crop.parcel.display_name,
            crop.parcel.barangay, crop.crop_type, crop.area_hectares,
            crop.cropping_schedule or "-", crop.planting_date or "-", crop.harvest_date or "-",
        ] for crop in queryset.order_by("parcel__barangay", "parcel__farmer__last_name", "parcel_id", "crop_type")]
        return "Commodity per Farm Parcel", ["Farmer ID", "Farmer", "Parcel", "Barangay", "Commodity", "Area (ha)", "Schedule", "Planting Date", "Harvest Date"], rows

    queryset = _filter_period(ServiceRequest.objects.filter(farmer__is_active=True), "created_at", date_range)
    if year:
        queryset = queryset.filter(created_at__year=int(year))
    if barangay:
        queryset = queryset.filter(farmer__barangay=barangay)
    if commodity:
        queryset = queryset.filter(farmer__parcels__crops__crop_type=commodity).distinct()
    if status:
        queryset = queryset.filter(status=status)
    data = queryset.values("status").annotate(total=Count("id")).order_by("status")
    labels = dict(ServiceRequest.STATUS_CHOICES)
    return "Service Request Status", ["Status", "Requests"], [[labels.get(item["status"], item["status"]), item["total"]] for item in data]


def _filename(title, extension):
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return f"fmis_{slug}_{timezone.localdate():%Y%m%d}.{extension}"


def _active_filter_rows(filters):
    return [[FILTER_LABELS[key], value] for key, value in (filters or {}).items() if key in FILTER_LABELS and value]


def _csv_response(title, headers, rows, date_range, filters=None):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{_filename(title, "csv")}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow([title])
    writer.writerow(["Date Range", DATE_RANGES[date_range]])
    for label, value in _active_filter_rows(filters):
        writer.writerow([label, value])
    writer.writerow(["Generated", timezone.localtime().strftime("%B %d, %Y %I:%M %p")])
    writer.writerow([])
    writer.writerow(headers)
    writer.writerows(rows)
    return response


def _pdf_response(title, headers, rows, date_range, filters=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_filename(title, "pdf")}"'
    document = SimpleDocTemplate(response, pagesize=landscape(A4), rightMargin=30, leftMargin=30, topMargin=28, bottomMargin=28, title=title)
    styles = getSampleStyleSheet()
    active_filters = ", ".join(f"{label}: {value}" for label, value in _active_filter_rows(filters)) or "None"
    story = [Paragraph("FMIS - Office for Agricultural Services", styles["Heading2"]), Paragraph(title, styles["Title"]), Paragraph(f"Date range: {DATE_RANGES[date_range]} | Filters: {active_filters} | Generated: {timezone.localtime():%B %d, %Y %I:%M %p}", styles["Normal"]), Spacer(1, 14)]
    table_data = [headers] + [[str(value if value is not None else "-") for value in row] for row in rows]
    if not rows:
        table_data.append(["No records found for the selected date range."] + [""] * (len(headers) - 1))
    table = Table(table_data, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153c2a")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#cfded4")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f8f3")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    document.build(story)
    return response


def generate_report(report_type, output_format, date_range, filters=None):
    if output_format not in FORMATS:
        raise ValueError("Choose CSV or PDF format.")
    title, headers, rows = build_report(report_type, date_range, filters)
    if output_format == "pdf":
        return _pdf_response(title, headers, rows, date_range, filters)
    return _csv_response(title, headers, rows, date_range, filters)


def farmers_csv():
    return generate_report("farmer_master", "csv", "all")
