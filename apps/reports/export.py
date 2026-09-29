import csv
import re
from calendar import monthrange

from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils import timezone

from apps.crops.models import CropRecord
from apps.activity_logs.models import ActivityLog
from apps.authentication.models import CustomUser
from apps.common.constants import ROSARIO_BARANGAYS
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest

REPORT_TEMPLATES = [
    {
        "key": "farmer_master",
        "title": "Farmer Master List",
        "description": "Active farmer IDs, contact details, barangay, and RSBSA numbers",
        "icon": "bi-people",
    },
    {
        "key": "farmers_by_barangay",
        "title": "Total Farmers per Barangay",
        "description": "Registered farmers grouped by Rosario barangay",
        "icon": "bi-geo-alt",
    },
    {
        "key": "farm_area_by_barangay",
        "title": "Total Farm Area per Barangay",
        "description": "Farm parcels and consolidated hectares grouped by barangay",
        "icon": "bi-map",
    },
    {
        "key": "farmers_by_ownership",
        "title": "Farmers by Land Ownership",
        "description": "Farmers, parcels, and area grouped by ownership or tenure",
        "icon": "bi-house-check",
    },
    {
        "key": "crop_summary",
        "title": "Crop Production Summary",
        "description": "Farmer count, crop records, and planted area by crop",
        "icon": "bi-flower1",
    },
    {
        "key": "commodity_per_parcel",
        "title": "Commodity per Farm Parcel",
        "description": "Each active parcel with its farmer and recorded commodities",
        "icon": "bi-grid-3x3-gap",
    },
    {
        "key": "service_status",
        "title": "Service Request Status",
        "description": "Farmer service requests grouped by current status",
        "icon": "bi-clipboard-check",
    },
]
REPORT_KEYS = {item["key"] for item in REPORT_TEMPLATES}
SYSTEM_REPORT_TEMPLATES = [
    {
        "key": "system_overview",
        "title": "System Overview",
        "description": "Accounts, activation status, and recorded system activity",
        "icon": "bi-speedometer2",
    },
    {
        "key": "user_accounts",
        "title": "User Account Registry",
        "description": "System users, roles, activation status, and last access",
        "icon": "bi-person-lock",
    },
    {
        "key": "activity_audit",
        "title": "Activity Audit Trail",
        "description": "Recorded system actions with user, module, and timestamp",
        "icon": "bi-clock-history",
    },
]
SYSTEM_REPORT_KEYS = {item["key"] for item in SYSTEM_REPORT_TEMPLATES}
DATE_RANGES = {
    "all": "All Records",
    "3": "Last 3 Months",
    "6": "Last 6 Months",
    "12": "Last 12 Months",
}
FORMATS = {"csv", "pdf"}
FILTER_LABELS = {
    "search": "Search",
    "year": "Year",
    "barangay": "Barangay",
    "commodity": "Commodity",
    "status": "Request Status",
    "sex": "Sex",
    "ownership": "Ownership",
    "record_status": "Record Status",
    "area": "Area",
    "crop_status": "Crop Status",
    "request_type": "Request Type",
    "priority": "Priority",
    "requested_date": "Date Requested",
    "role": "User Role",
    "account_status": "Account Status",
    "module": "Activity Module",
}


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
        queryset = _filter_period(
            Farmer.objects.filter(is_active=True).prefetch_related("parcels__crops"),
            "created_at",
            date_range,
        )
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(
                parcels__crops__crop_type=commodity,
                parcels__crops__is_active=True,
            ).distinct()
        rows = [
            [
                farmer.record_id,
                farmer.full_name,
                farmer.barangay,
                farmer.primary_commodity,
                farmer.phone_number or "-",
                farmer.rsbsa_number or "-",
                farmer.remarks or "-",
            ]
            for farmer in queryset.order_by("last_name", "first_name")
        ]
        return (
            "Farmer Master List",
            [
                "Farmer ID",
                "Farmer Name",
                "Barangay",
                "Primary Commodity",
                "Phone",
                "RSBSA Number",
                "Remarks",
            ],
            rows,
        )

    if report_type == "farmers_by_barangay":
        queryset = _filter_period(Farmer.objects.filter(is_active=True), "created_at", date_range)
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(
                parcels__crops__crop_type=commodity,
                parcels__crops__is_active=True,
            ).distinct()
        data = queryset.values("barangay").annotate(total=Count("id")).order_by("barangay")
        return (
            "Total Farmers per Barangay",
            ["Barangay", "Registered Farmers"],
            [[item["barangay"], item["total"]] for item in data],
        )

    if report_type == "farm_area_by_barangay":
        queryset = _filter_period(
            FarmParcel.objects.filter(is_active=True, farmer__is_active=True),
            "created_at",
            date_range,
        )
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity, crops__is_active=True).distinct()
        data = (
            queryset.values("barangay")
            .annotate(parcels=Count("id"), area=Sum("area_hectares"))
            .order_by("barangay")
        )
        return (
            "Total Farm Area per Barangay",
            ["Barangay", "Farm Parcels", "Total Area (ha)"],
            [[item["barangay"], item["parcels"], item["area"] or 0] for item in data],
        )

    if report_type == "farmers_by_ownership":
        queryset = _filter_period(
            FarmParcel.objects.filter(is_active=True, farmer__is_active=True),
            "created_at",
            date_range,
        )
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity, crops__is_active=True).distinct()
        data = (
            queryset.values("ownership_type")
            .annotate(
                farmers=Count("farmer", distinct=True),
                parcels=Count("id"),
                area=Sum("area_hectares"),
            )
            .order_by("ownership_type")
        )
        labels = dict(FarmParcel.OWNERSHIP_CHOICES)
        return (
            "Farmers by Land Ownership",
            ["Ownership / Tenure", "Farmers", "Parcels", "Area (ha)"],
            [
                [
                    labels.get(item["ownership_type"], item["ownership_type"]),
                    item["farmers"],
                    item["parcels"],
                    item["area"] or 0,
                ]
                for item in data
            ],
        )

    if report_type == "crop_summary":
        queryset = _filter_period(
            CropRecord.objects.filter(
                is_active=True, parcel__is_active=True, parcel__farmer__is_active=True
            ),
            "planting_date",
            date_range,
            date_only=True,
        )
        if year:
            queryset = queryset.filter(planting_date__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
        data = (
            queryset.values("crop_type")
            .annotate(
                farmers=Count("parcel__farmer", distinct=True),
                records=Count("id"),
                area=Sum("area_hectares"),
            )
            .order_by("crop_type")
        )
        return (
            "Crop Production Summary",
            ["Crop / Commodity", "Farmers", "Crop Records", "Planted Area (ha)"],
            [
                [item["crop_type"], item["farmers"], item["records"], item["area"] or 0]
                for item in data
            ],
        )

    if report_type == "commodity_per_parcel":
        queryset = _filter_period(
            CropRecord.objects.filter(
                is_active=True, parcel__is_active=True, parcel__farmer__is_active=True
            ).select_related("parcel__farmer"),
            "planting_date",
            date_range,
            date_only=True,
        )
        if year:
            queryset = queryset.filter(planting_date__year=int(year))
        if barangay:
            queryset = queryset.filter(parcel__barangay=barangay)
        if commodity:
            queryset = queryset.filter(crop_type=commodity)
        rows = [
            [
                crop.parcel.farmer.record_id,
                crop.parcel.farmer.full_name,
                crop.parcel.display_name,
                crop.parcel.barangay,
                crop.crop_type,
                crop.area_hectares,
                crop.planting_date or "-",
            ]
            for crop in queryset.order_by(
                "parcel__barangay", "parcel__farmer__last_name", "parcel_id", "crop_type"
            )
        ]
        return (
            "Commodity per Farm Parcel",
            [
                "Farmer ID",
                "Farmer",
                "Parcel",
                "Barangay",
                "Commodity",
                "Area (ha)",
                "Planting Date",
            ],
            rows,
        )

    queryset = _filter_period(
        ServiceRequest.objects.filter(farmer__is_active=True), "created_at", date_range
    )
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
    data = queryset.values("status").annotate(total=Count("id")).order_by("status")
    labels = dict(ServiceRequest.STATUS_CHOICES)
    return (
        "Service Request Status",
        ["Status", "Requests"],
        [[labels.get(item["status"], item["status"]), item["total"]] for item in data],
    )


def build_system_report(report_type, date_range, filters=None):
    if report_type not in SYSTEM_REPORT_KEYS or date_range not in DATE_RANGES:
        raise ValueError("Choose a valid system report and date range.")

    filters = filters or {}
    role = str(filters.get("role", "")).strip()
    account_status = str(filters.get("account_status", "")).strip()
    module = str(filters.get("module", "")).strip()
    if role and role not in {"ADMIN", "STAFF"}:
        raise ValueError("Choose a valid user role.")
    if account_status and account_status not in {"ACTIVE", "INACTIVE", "PENDING"}:
        raise ValueError("Choose a valid account status.")

    accounts = _filter_period(CustomUser.objects.all(), "date_joined", date_range)
    if role:
        accounts = accounts.filter(role=role)
    if account_status == "ACTIVE":
        accounts = accounts.filter(is_active=True, activation_pending=False)
    elif account_status == "INACTIVE":
        accounts = accounts.filter(is_active=False, activation_pending=False)
    elif account_status == "PENDING":
        accounts = accounts.filter(activation_pending=True)

    activities = _filter_period(
        ActivityLog.objects.select_related("actor"),
        "created_at",
        date_range,
    )
    if role:
        activities = activities.filter(actor__role=role)
    if module:
        activities = activities.filter(module=module)

    if report_type == "system_overview":
        return (
            "FMIS System Overview",
            ["System Indicator", "Total"],
            [
                ["User Accounts", accounts.count()],
                ["Active Accounts", accounts.filter(is_active=True).count()],
                ["Pending Activations", accounts.filter(activation_pending=True).count()],
                ["Administrator Accounts", accounts.filter(role="ADMIN").count()],
                ["Staff Accounts", accounts.filter(role="STAFF").count()],
                ["Recorded System Activities", activities.count()],
            ],
        )

    if report_type == "user_accounts":
        rows = []
        for account in accounts.order_by("role", "username"):
            if account.activation_pending:
                status = "Pending activation"
            elif account.is_active:
                status = "Active"
            else:
                status = "Inactive"
            rows.append(
                [
                    account.username,
                    account.display_name,
                    account.email or "-",
                    account.phone_number or "-",
                    account.get_role_display(),
                    status,
                    timezone.localtime(account.date_joined).strftime("%b %d, %Y %I:%M %p"),
                    (
                        timezone.localtime(account.last_login).strftime("%b %d, %Y %I:%M %p")
                        if account.last_login
                        else "Never"
                    ),
                ]
            )
        return (
            "User Account Registry",
            ["Username", "Name", "Email", "Phone", "Role", "Status", "Created", "Last Access"],
            rows,
        )

    if report_type == "activity_audit":
        rows = [
            [
                timezone.localtime(log.created_at).strftime("%b %d, %Y %I:%M:%S %p"),
                log.actor.display_name if log.actor else "System",
                log.module or "FMIS",
                log.title or log.action,
                log.target_label or "-",
                log.reason or "-",
                log.status,
            ]
            for log in activities.order_by("-created_at")
        ]
        return (
            "Activity Audit Trail",
            ["Date and Time", "User", "Module", "Activity", "Affected Record", "Reason", "Status"],
            rows,
        )

    raise ValueError("Choose a valid system report.")


def _filename(title, extension):
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return f"fmis_{slug}_{timezone.localdate():%Y%m%d}.{extension}"


def _active_filter_rows(filters):
    return [
        [FILTER_LABELS[key], value]
        for key, value in (filters or {}).items()
        if key in FILTER_LABELS and value
    ]


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
    from pathlib import Path
    from xml.sax.saxutils import escape

    from django.conf import settings
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_filename(title, "pdf")}"'
    document = SimpleDocTemplate(
        response,
        pagesize=landscape(A4),
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=31 * mm,
        bottomMargin=16 * mm,
        title=title,
        author="Office for Agricultural Services - Rosario, Batangas",
        subject="FMIS generated management report",
    )
    styles = getSampleStyleSheet()
    generated_at = timezone.localtime()
    active_filter_rows = _active_filter_rows(filters)
    active_filters = ", ".join(
        f"{label}: {value}" for label, value in active_filter_rows
    ) or "None"

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#153c2a"),
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#5f6f66"),
    )
    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=6.5,
        leading=8,
        textColor=colors.HexColor("#527061"),
        spaceAfter=2,
    )
    meta_value_style = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=11,
        textColor=colors.HexColor("#18271f"),
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.2,
        leading=9,
        textColor=colors.white,
        alignment=TA_LEFT,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=9.2,
        textColor=colors.HexColor("#17231d"),
        alignment=TA_LEFT,
    )

    summary = Table(
        [[
            [Paragraph("DATE RANGE", meta_label_style), Paragraph(escape(DATE_RANGES[date_range]), meta_value_style)],
            [Paragraph("RECORDS", meta_label_style), Paragraph(f"{len(rows):,}", meta_value_style)],
            [Paragraph("GENERATED", meta_label_style), Paragraph(generated_at.strftime("%b %d, %Y - %I:%M %p"), meta_value_style)],
        ]],
        colWidths=[document.width * .30, document.width * .20, document.width * .50],
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f7f2")),
        ("BOX", (0, 0), (-1, -1), .6, colors.HexColor("#c8ddce")),
        ("INNERGRID", (0, 0), (-1, -1), .4, colors.HexColor("#d7e6db")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story = [
        Paragraph(escape(title), title_style),
        Paragraph("Official FMIS operational report for Rosario, Batangas", subtitle_style),
        Spacer(1, 8),
        summary,
        Spacer(1, 7),
        Paragraph(f"<b>Applied filters:</b> {escape(active_filters)}", subtitle_style),
        Spacer(1, 12),
    ]

    string_rows = [[str(value if value not in (None, "") else "-") for value in row] for row in rows]
    table_data = [[Paragraph(escape(str(header)), header_style) for header in headers]] + [
        [Paragraph(escape(value), cell_style) for value in row] for row in string_rows
    ]
    if not rows:
        table_data.append(
            [Paragraph("No records found for the selected report criteria.", cell_style)]
            + [Paragraph("", cell_style)] * (len(headers) - 1)
        )

    lengths = []
    for index, header in enumerate(headers):
        values = [str(row[index]) for row in string_rows if index < len(row)]
        sample_length = max([len(str(header)), *(min(len(value), 42) for value in values)] or [8])
        lengths.append(max(7, min(sample_length, 30)))
    total_weight = sum(lengths) or 1
    column_widths = [document.width * weight / total_weight for weight in lengths]
    table = Table(table_data, colWidths=column_widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#153c2a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, 0), .4, colors.HexColor("#6e8c7b")),
                ("LINEBELOW", (0, 1), (-1, -1), .35, colors.HexColor("#d5e2d9")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f8f5")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, 0), 7),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
                ("TOPPADDING", (0, 1), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
                ("SPAN", (0, 1), (-1, 1)) if not rows else ("LEFTPADDING", (0, 1), (-1, -1), 7),
            ]
        )
    )
    story.append(table)

    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "brand" / "fmis-logo.png"

    def decorate_page(canvas, doc):
        page_width, page_height = landscape(A4)
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#112f23"))
        canvas.rect(0, page_height - 24 * mm, page_width, 24 * mm, fill=1, stroke=0)
        if logo_path.exists():
            canvas.drawImage(
                str(logo_path),
                14 * mm,
                page_height - 20.5 * mm,
                15 * mm,
                15 * mm,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(33 * mm, page_height - 10.5 * mm, "OFFICE FOR AGRICULTURAL SERVICES")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#d6e8dc"))
        canvas.drawString(33 * mm, page_height - 15 * mm, "Municipality of Rosario, Batangas")
        canvas.drawString(33 * mm, page_height - 19 * mm, "Farmer Management Information System")
        canvas.setFillColor(colors.HexColor("#d8a62a"))
        canvas.rect(0, page_height - 24.7 * mm, page_width, .7 * mm, fill=1, stroke=0)

        canvas.setStrokeColor(colors.HexColor("#c8d8cd"))
        canvas.setLineWidth(.5)
        canvas.line(14 * mm, 12 * mm, page_width - 14 * mm, 12 * mm)
        canvas.setFillColor(colors.HexColor("#607067"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(14 * mm, 8 * mm, "FMIS generated report - For authorized municipal use")
        canvas.drawRightString(page_width - 14 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    return response


def generate_report(report_type, output_format, date_range, filters=None):
    if output_format not in FORMATS:
        raise ValueError("Choose CSV or PDF format.")
    title, headers, rows = build_report(report_type, date_range, filters)
    if output_format == "pdf":
        return _pdf_response(title, headers, rows, date_range, filters)
    return _csv_response(title, headers, rows, date_range, filters)


def generate_system_report(report_type, output_format, date_range, filters=None):
    if output_format not in FORMATS:
        raise ValueError("Choose CSV or PDF format.")
    title, headers, rows = build_system_report(report_type, date_range, filters)
    if output_format == "pdf":
        return _pdf_response(title, headers, rows, date_range, filters)
    return _csv_response(title, headers, rows, date_range, filters)


def generate_table_export(title, headers, rows, output_format, filters=None):
    """Export a management table without routing the user through report previews."""
    if output_format not in FORMATS:
        raise ValueError("Choose CSV or PDF format.")
    if output_format == "pdf":
        return _pdf_response(title, headers, rows, "all", filters)
    return _csv_response(title, headers, rows, "all", filters)


def farmers_csv():
    return generate_report("farmer_master", "csv", "all")
