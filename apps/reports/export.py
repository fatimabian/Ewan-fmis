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
from apps.interventions.models import Intervention
from apps.service_requests.models import ServiceRequest

REPORT_TEMPLATES = [
    {
        "key": "farmer_master",
        "title": "Farmer Master List",
        "description": "Complete farmer profile, registration, parcel, crop, and supporting-record information",
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
    {
        "key": "intervention_summary",
        "title": "Intervention Distribution Summary",
        "description": "Interventions provided and farmers served by type",
        "icon": "bi-box-seam",
    },
    {
        "key": "intervention_registry",
        "title": "Complete Intervention Register",
        "description": "Every delivered intervention with farmer, quantity, provider, request, and recorder",
        "icon": "bi-table",
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
    "intervention_type": "Intervention Type",
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


def _yes_no(value):
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "Not recorded"


def _local_datetime(value):
    return timezone.localtime(value).strftime("%b %d, %Y %I:%M %p") if value else "-"


def build_report(report_type, date_range, filters=None, compact=False):
    if report_type not in REPORT_KEYS or date_range not in DATE_RANGES:
        raise ValueError("Choose a valid report template and date range.")
    filters = filters or {}
    year = str(filters.get("year", "")).strip()
    barangay = str(filters.get("barangay", "")).strip()
    commodity = str(filters.get("commodity", "")).strip()
    status = str(filters.get("status", "")).strip()
    intervention_type = str(filters.get("intervention_type", "")).strip()
    if year and (not year.isdigit() or len(year) != 4):
        raise ValueError("Choose a valid report year.")
    if barangay and barangay not in ROSARIO_BARANGAYS:
        raise ValueError("Choose a valid Rosario barangay.")
    if commodity and len(commodity) > 100:
        raise ValueError("Choose a valid commodity.")
    if report_type == "service_status" and status and status not in dict(ServiceRequest.STATUS_CHOICES):
        raise ValueError("Choose a valid request status.")
    if (
        report_type in {"intervention_summary", "intervention_registry"}
        and intervention_type
        and intervention_type not in dict(Intervention.TYPE_CHOICES)
    ):
        raise ValueError("Choose a valid intervention type.")

    if report_type == "farmer_master":
        queryset = _filter_period(
            Farmer.objects.filter(is_active=True)
            .select_related("last_updated_by")
            .prefetch_related("documents", "parcels__crops", "parcels__photos"),
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
        rows = []
        for farmer in queryset.order_by("pk"):
            parcels = [parcel for parcel in farmer.parcels.all() if parcel.is_active]
            crops = [crop for parcel in parcels for crop in parcel.crops.all() if crop.is_active]
            documents = list(farmer.documents.all())
            parcel_details = []
            for parcel in parcels:
                parcel_details.append(
                    f"{parcel.display_name}: {parcel.area_hectares} ha; {parcel.barangay}, "
                    f"{parcel.municipality}, {parcel.province}; tenure={parcel.get_ownership_type_display()}; "
                    f"land={parcel.get_land_type_display()}; farm={parcel.get_farm_type_display() or 'Not recorded'}; "
                    f"ancestral domain={_yes_no(parcel.within_ancestral_domain)}; ARB={_yes_no(parcel.agrarian_reform_beneficiary)}; "
                    f"ownership document={parcel.get_ownership_document_display() or parcel.ownership_document_other or 'Not recorded'}; "
                    f"land owner={parcel.land_owner_name or 'Not recorded'}; owner in RSBSA={_yes_no(parcel.land_owner_registered_rsbsa)}; "
                    f"owner RSBSA={parcel.land_owner_rsbsa_number or 'Not recorded'}; georeference={parcel.georef_id or 'Not recorded'}; "
                    f"GPX status={parcel.get_gpx_status_display()}; coordinates={parcel.coordinates or 'Not recorded'}; "
                    f"rotational tiller={_yes_no(parcel.rotational_tiller)}; remarks={parcel.remarks or 'None'}"
                )
            crop_details = [
                f"{crop.crop_type} ({crop.parcel.display_name}): {crop.area_hectares} ha; "
                f"schedule={crop.cropping_schedule or 'Not recorded'}; heads={crop.number_of_heads or 'Not recorded'}; "
                f"organic={_yes_no(crop.is_organic)}; intercrop={_yes_no(crop.is_intercrop)}; "
                f"planted={crop.planting_date or 'Not recorded'}; harvest={crop.harvest_date or 'Not recorded'}"
                for crop in crops
            ]
            if compact:
                rows.append([
                    farmer.record_id,
                    farmer.full_name,
                    farmer.rsbsa_number or "Not assigned",
                    farmer.get_registration_status_display(),
                    farmer.barangay,
                    farmer.phone_number or "-",
                    farmer.get_livelihood_display(),
                    f"{len(parcels)} parcel(s) · {len(crops)} crop(s)",
                ])
                continue
            document_details = [
                f"{document.get_document_type_display()}"
                + (f" - {document.description}" if document.description else "")
                for document in documents
            ]
            rows.append([
                farmer.record_id, farmer.registration_reference, farmer.rsbsa_number or "-",
                farmer.get_registration_status_display(), farmer.last_name, farmer.first_name,
                farmer.middle_name or "-", farmer.extension_name or "-", farmer.full_name,
                farmer.get_sex_display() or "-", farmer.birth_date or "-",
                farmer.age if farmer.age is not None else "-", farmer.place_of_birth or "-",
                farmer.house_lot_purok or "-", farmer.street_sitio or "-", farmer.barangay,
                farmer.city_municipality, farmer.province, farmer.region,
                farmer.mother_maiden_name or "-", farmer.phone_number or "-", farmer.email or "-",
                farmer.get_civil_status_display() or "-", farmer.spouse_name or "-",
                farmer.highest_education or "-", farmer.valid_id_type or "-", farmer.valid_id_number or "-",
                farmer.religion or "-", _yes_no(farmer.is_indigenous), farmer.indigenous_group or "-",
                _yes_no(farmer.is_pwd), _yes_no(farmer.is_four_ps), farmer.get_livelihood_display(),
                farmer.activities_display or "-", _yes_no(farmer.philsys_registered), farmer.philsys_pcn or "-",
                farmer.philsys_trn or "-", farmer.fca_membership or "-", farmer.location_coordinates or "-",
                _yes_no(farmer.consent_given), farmer.remarks or "-", _local_datetime(farmer.submitted_at),
                _local_datetime(farmer.created_at), _local_datetime(farmer.last_updated_at),
                farmer.last_updated_by.display_name if farmer.last_updated_by else "-",
                len(documents), "; ".join(document_details) or "None",
                len(parcels), sum((parcel.area_hectares for parcel in parcels), 0),
                " | ".join(parcel_details) or "No active parcel",
                len(crops), " | ".join(crop_details) or "No active crop",
                sum(1 for parcel in parcels for photo in parcel.photos.all() if photo.is_active),
            ])
        if compact:
            return (
                "Farmer Master List",
                [
                    "Farmer ID", "Farmer Name", "RSBSA ID", "Status", "Barangay",
                    "Phone", "Livelihood", "Farm Records",
                ],
                rows,
            )
        return (
            "Farmer Master List",
            [
                "Farmer ID", "Registration Reference", "RSBSA Number", "Registration Status",
                "Last Name", "First Name", "Middle Name", "Extension", "Full Name", "Sex",
                "Birth Date", "Age", "Place of Birth", "House / Lot / Purok", "Street / Sitio",
                "Barangay", "Municipality", "Province", "Region", "Mother's Maiden Name",
                "Phone", "Email", "Civil Status", "Spouse", "Highest Education", "Valid ID Type",
                "Valid ID Number", "Religion", "Indigenous Person", "Indigenous Group", "PWD",
                "4Ps Member", "Livelihood", "Livelihood Activities", "PhilSys Registered",
                "PhilSys PCN", "PhilSys TRN", "FCA Membership", "Home Coordinates", "Consent Given",
                "Farmer Remarks", "Submitted At", "Date Registered", "Last Updated", "Last Updated By",
                "Document Count", "Supporting Documents", "Parcel Count", "Total Parcel Area (ha)",
                "Complete Farm Parcel Details", "Crop Record Count", "Complete Crop Details",
                "Field Photo Count",
            ],
            rows,
        )

    if report_type == "farmers_by_barangay":
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
        return (
            "Total Farmers per Barangay",
            ["Barangay", "Farmer ID", "Farmer", "Primary Commodity", "Phone", "Date Registered"],
            [
                [
                    farmer.barangay,
                    farmer.record_id,
                    farmer.full_name,
                    farmer.primary_commodity,
                    farmer.phone_number or "-",
                    timezone.localtime(farmer.created_at).date(),
                ]
                for farmer in queryset.order_by("barangay", "last_name", "first_name")
            ],
        )

    if report_type == "farm_area_by_barangay":
        queryset = _filter_period(
            FarmParcel.objects.filter(is_active=True, farmer__is_active=True).select_related("farmer"),
            "created_at",
            date_range,
        )
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity, crops__is_active=True).distinct()
        return (
            "Total Farm Area per Barangay",
            ["Barangay", "Farmer ID", "Farmer", "Parcel", "Area (ha)", "Ownership", "Date Added"],
            [
                [
                    parcel.barangay,
                    parcel.farmer.record_id,
                    parcel.farmer.full_name,
                    parcel.display_name,
                    parcel.area_hectares,
                    parcel.get_ownership_type_display(),
                    timezone.localtime(parcel.created_at).date(),
                ]
                for parcel in queryset.order_by("barangay", "farmer__last_name", "pk")
            ],
        )

    if report_type == "farmers_by_ownership":
        queryset = _filter_period(
            FarmParcel.objects.filter(is_active=True, farmer__is_active=True).select_related("farmer"),
            "created_at",
            date_range,
        )
        if year:
            queryset = queryset.filter(created_at__year=int(year))
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if commodity:
            queryset = queryset.filter(crops__crop_type=commodity, crops__is_active=True).distinct()
        return (
            "Farmers by Land Ownership",
            ["Ownership / Tenure", "Farmer ID", "Farmer", "Barangay", "Parcel", "Area (ha)", "Land Owner"],
            [
                [
                    parcel.get_ownership_type_display(),
                    parcel.farmer.record_id,
                    parcel.farmer.full_name,
                    parcel.barangay,
                    parcel.display_name,
                    parcel.area_hectares,
                    parcel.land_owner_name or "-",
                ]
                for parcel in queryset.order_by("ownership_type", "farmer__last_name", "pk")
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
        return (
            "Crop Production Summary",
            ["Crop / Commodity", "Farmer ID", "Farmer", "Barangay", "Parcel", "Area (ha)", "Planting Date"],
            [
                [
                    crop.crop_type,
                    crop.parcel.farmer.record_id,
                    crop.parcel.farmer.full_name,
                    crop.parcel.barangay,
                    crop.parcel.display_name,
                    crop.area_hectares,
                    crop.planting_date or "-",
                ]
                for crop in queryset.select_related("parcel__farmer").order_by(
                    "crop_type", "parcel__farmer__last_name", "pk"
                )
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

    if report_type == "intervention_summary":
        queryset = _filter_period(
            Intervention.objects.filter(is_active=True, farmer__is_active=True),
            "intervention_date",
            date_range,
            date_only=True,
        )
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
        data = (
            queryset.values("intervention_type")
            .annotate(
                interventions=Count("id"),
                farmers=Count("farmer", distinct=True),
            )
            .order_by("intervention_type")
        )
        labels = dict(Intervention.TYPE_CHOICES)
        return (
            "Intervention Distribution Summary",
            ["Intervention Type", "Interventions Given", "Farmers Served"],
            [
                [
                    labels.get(item["intervention_type"], item["intervention_type"]),
                    item["interventions"],
                    item["farmers"],
                ]
                for item in data
            ],
        )

    if report_type == "intervention_registry":
        queryset = _filter_period(
            Intervention.objects.filter(is_active=True, farmer__is_active=True)
            .select_related("farmer", "service_request", "recorded_by"),
            "intervention_date",
            date_range,
            date_only=True,
        )
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
        rows = [
            [
                item.reference_id,
                item.intervention_date,
                item.farmer.record_id,
                item.farmer.full_name,
                item.farmer.barangay,
                item.get_intervention_type_display(),
                item.description,
                f"{item.quantity} {item.unit}".strip() if item.quantity is not None else "-",
                item.provider or "-",
                item.service_request.request_id if item.service_request else "-",
                item.recorded_by.display_name if item.recorded_by else "-",
            ]
            for item in queryset.order_by("pk")
        ]
        return (
            "Complete Intervention Register",
            [
                "Reference", "Date", "Farmer ID", "Farmer", "Barangay", "Intervention Type",
                "Description", "Quantity", "Provider", "Service Request", "Recorded By",
            ],
            rows,
        )

    queryset = _filter_period(
        ServiceRequest.objects.filter(farmer__is_active=True).select_related(
            "farmer", "service", "assigned_to"
        ),
        "created_at",
        date_range,
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
    return (
        "Service Request Status",
        [
            "Request ID", "Farmer ID", "Farmer", "Barangay", "Request Type",
            "Request", "Status", "Priority", "Date Requested", "Assigned Staff",
        ],
        [
            [
                item.request_id,
                item.farmer.record_id,
                item.farmer.full_name,
                item.farmer.barangay,
                item.service.name,
                item.subject,
                item.get_status_display(),
                item.get_priority_display(),
                timezone.localtime(item.created_at).date(),
                item.assigned_to.display_name if item.assigned_to else "Unassigned",
            ]
            for item in queryset.order_by("pk")
        ],
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
    def safe_cell(value):
        """Prevent spreadsheet software from executing exported user text as a formula."""
        if value is None:
            return ""
        text = str(value)
        if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
            return "'" + text
        return value

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
    writer.writerow([safe_cell(value) for value in headers])
    writer.writerows([[safe_cell(value) for value in row] for row in rows])
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


def _farmer_master_pdf_response(title, headers, rows, date_range, filters=None):
    """Render a concise printable master list; CSV retains the complete dataset."""
    from pathlib import Path
    from xml.sax.saxutils import escape

    from django.conf import settings
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "MasterTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=18, leading=22, textColor=colors.HexColor("#153c2a"), alignment=TA_LEFT,
    )
    farmer_style = ParagraphStyle(
        "FarmerTitle", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, textColor=colors.HexColor("#153c2a"), spaceAfter=7,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading3"], fontName="Helvetica-Bold",
        fontSize=8, leading=10, textColor=colors.white, spaceBefore=7, spaceAfter=0,
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=6.8, leading=8.4, textColor=colors.HexColor("#50665a"),
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["Normal"], fontName="Helvetica",
        fontSize=7.2, leading=9.2, textColor=colors.HexColor("#17231d"),
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontSize=8, leading=11,
        textColor=colors.HexColor("#5f6f66"),
    )
    header_lookup = {header: index for index, header in enumerate(headers)}

    def value(row, header):
        item = row[header_lookup[header]] if header in header_lookup else "-"
        return str(item if item not in (None, "") else "-")

    def section(title_text, fields, row):
        heading = Table([[Paragraph(escape(title_text.upper()), section_style)]], colWidths=[document.width])
        heading.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#26734b")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        pairs = []
        for index in range(0, len(fields), 2):
            first = fields[index]
            second = fields[index + 1] if index + 1 < len(fields) else None
            cells = [Paragraph(escape(first), label_style), Paragraph(escape(value(row, first)), value_style)]
            if second:
                cells += [Paragraph(escape(second), label_style), Paragraph(escape(value(row, second)), value_style)]
            else:
                cells += [Paragraph("", label_style), Paragraph("", value_style)]
            pairs.append(cells)
        table = Table(
            pairs,
            colWidths=[document.width * .16, document.width * .34, document.width * .16, document.width * .34],
            hAlign="LEFT",
        )
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#d8e5dc")),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f9f6")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return [heading, table]

    story = [
        Paragraph(escape(title), title_style),
        Paragraph(
            f"Complete active farmer records · {len(rows):,} farmer(s) · "
            f"Date range: {escape(DATE_RANGES[date_range])}",
            subtitle_style,
        ),
        Spacer(1, 10),
    ]
    farmer_fields = [
        "RSBSA Number", "Sex", "Birth Date", "Livelihood", "Barangay", "Municipality",
        "Phone", "Email",
    ]
    farm_fields = [
        "Parcel Count", "Total Parcel Area (ha)", "Farm Parcel Summary", "Crop Record Count",
        "Crop Summary",
    ]
    for index, row in enumerate(rows):
        if index:
            story.append(Spacer(1, 12))
        story.append(
            Paragraph(
                f"{escape(value(row, 'Farmer ID'))} · {escape(value(row, 'Full Name'))}",
                farmer_style,
            )
        )
        story.extend(section("Farmer information", farmer_fields, row))
        story.extend(section("Farm parcels and crops", farm_fields, row))

    if not rows:
        story.append(Paragraph("No farmers matched the selected report criteria.", value_style))

    logo_path = Path(settings.BASE_DIR) / "static" / "images" / "brand" / "fmis-logo.png"

    def decorate_page(canvas, doc):
        page_width, page_height = landscape(A4)
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#112f23"))
        canvas.rect(0, page_height - 24 * mm, page_width, 24 * mm, fill=1, stroke=0)
        if logo_path.exists():
            canvas.drawImage(str(logo_path), 14 * mm, page_height - 20.5 * mm, 15 * mm, 15 * mm,
                             preserveAspectRatio=True, anchor="c", mask="auto")
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(33 * mm, page_height - 10.5 * mm, "OFFICE FOR AGRICULTURAL SERVICES")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#d6e8dc"))
        canvas.drawString(33 * mm, page_height - 15 * mm, "Municipality of Rosario, Batangas")
        canvas.drawString(33 * mm, page_height - 19 * mm, "Complete Farmer Master List")
        canvas.setStrokeColor(colors.HexColor("#c8d8cd"))
        canvas.line(14 * mm, 12 * mm, page_width - 14 * mm, 12 * mm)
        canvas.setFillColor(colors.HexColor("#607067"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(14 * mm, 8 * mm, "Confidential FMIS report - Authorized municipal use only")
        canvas.drawRightString(page_width - 14 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate_page, onLaterPages=decorate_page)
    return response


def generate_report(report_type, output_format, date_range, filters=None):
    if output_format not in FORMATS:
        raise ValueError("Choose CSV or PDF format.")
    title, headers, rows = build_report(
        report_type,
        date_range,
        filters,
        compact=output_format == "pdf" and report_type == "farmer_master",
    )
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
