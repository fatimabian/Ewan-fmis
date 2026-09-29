from datetime import date

from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.common.constants import ROSARIO_BARANGAYS
from apps.crops.models import CropRecord
from apps.activity_logs.models import ActivityLog
from apps.activity_logs.services import record_request_event
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest
from .analytics import report_metrics, report_preview
from .export import (
    DATE_RANGES,
    REPORT_TEMPLATES,
    SYSTEM_REPORT_TEMPLATES,
    build_report,
    build_system_report,
    farmers_csv,
    generate_report,
    generate_system_report,
    generate_table_export,
)


class ReportsView(FMISLoginRequiredMixin, TemplateView):
    template_name = "reports/home.html"

    @staticmethod
    def _filters(source):
        return {
            "year": source.get("year", ""),
            "barangay": source.get("barangay", ""),
            "commodity": source.get("commodity", ""),
            "status": source.get("status", ""),
            "role": source.get("role", ""),
            "account_status": source.get("account_status", ""),
            "module": source.get("module", ""),
        }

    def get_context_data(self, **kwargs):
        current_year = date.today().year
        source = kwargs.pop("form_data", self.request.GET)
        filters = self._filters(source)
        date_range = source.get("date_range", "all")
        if date_range not in DATE_RANGES:
            date_range = "all"
        selected_report_type = source.get("report_type", "")
        system_report = self.request.user.is_admin
        preview = None
        report_error = ""
        try:
            if selected_report_type:
                preview = report_preview(
                    selected_report_type,
                    date_range,
                    filters,
                    system_report=system_report,
                )
            else:
                if system_report:
                    build_system_report("system_overview", date_range, filters)
                else:
                    build_report("farmer_master", date_range, filters)
        except ValueError as error:
            report_error = str(error)
            filters = {"year": "", "barangay": "", "commodity": "", "status": ""}
            date_range = "all"
        context = {
            **super().get_context_data(**kwargs),
            **report_metrics(date_range, filters),
            "base_template": (
                "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
            ),
            "report_templates": (
                SYSTEM_REPORT_TEMPLATES if system_report else REPORT_TEMPLATES
            ),
            "date_ranges": DATE_RANGES,
            "report_years": range(current_year, current_year - 11, -1),
            "barangays": ROSARIO_BARANGAYS,
            "commodities": CropRecord.objects.filter(is_active=True).exclude(crop_type="")
            .values_list("crop_type", flat=True)
            .distinct()
            .order_by("crop_type"),
            "status_choices": ServiceRequest.STATUS_CHOICES,
            "role_choices": (("ADMIN", "Administrator"), ("STAFF", "Staff")),
            "account_status_choices": (
                ("ACTIVE", "Active"),
                ("PENDING", "Pending Activation"),
                ("INACTIVE", "Inactive"),
            ),
            "activity_modules": ActivityLog.objects.exclude(module="")
            .values_list("module", flat=True)
            .distinct()
            .order_by("module"),
            "selected_report_type": selected_report_type,
            "selected_date_range": date_range,
            "selected_filters": filters,
            "report_preview": preview,
            "report_error": report_error,
        }
        return context

    def post(self, request, *args, **kwargs):
        try:
            generator = generate_system_report if request.user.is_admin else generate_report
            response = generator(
                request.POST.get("report_type", ""),
                request.POST.get("format", ""),
                request.POST.get("date_range", ""),
                {
                    "year": request.POST.get("year", ""),
                    "barangay": request.POST.get("barangay", ""),
                    "commodity": request.POST.get("commodity", ""),
                    "status": request.POST.get("status", ""),
                    "role": request.POST.get("role", ""),
                    "account_status": request.POST.get("account_status", ""),
                    "module": request.POST.get("module", ""),
                },
            )
            record_request_event(
                request,
                title="Report Exported",
                module="Reports",
                description=f"{request.user.display_name} exported an FMIS report.",
                target_label=request.POST.get("report_type", "Unspecified report")[:255],
                details=[{"field": "Format", "after": request.POST.get("format", "").upper()}],
            )
            return response
        except (ValueError, ImportError) as error:
            context = self.get_context_data(form_data=request.POST)
            context["report_error"] = str(error) or "The report could not be generated."
            return self.render_to_response(context, status=400)


class FarmerExportView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def get(self, request):
        response = farmers_csv()
        record_request_event(
            request,
            title="Farmer Data Exported",
            module="Reports",
            description=f"{request.user.display_name} exported the farmer management list.",
            target_label="Farmer Management List",
        )
        return response


class ManagementTableExportView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Download the currently filtered operational table as CSV or PDF."""

    def _dataset(self, request, dataset):
        if dataset == "farmers":
            from apps.farmers.views import FarmerListView

            view = FarmerListView()
            view.request = request
            rows = [
                [
                    farmer.record_id,
                    farmer.list_name,
                    farmer.barangay,
                    farmer.phone_number or "-",
                    farmer.get_livelihood_display(),
                    "Active" if farmer.is_active else "Archived",
                ]
                for farmer in view.get_queryset()
            ]
            filters = {
                "search": request.GET.get("q", ""),
                "barangay": request.GET.get("barangay", ""),
                "sex": dict(Farmer.SEX_CHOICES).get(
                    request.GET.get("sex", ""), request.GET.get("sex", "")
                ),
            }
            return (
                "Farmer Management List",
                [
                    "Farmer ID",
                    "Farmer Name",
                    "Barangay",
                    "Contact Number",
                    "Livelihood",
                    "Status",
                ],
                rows,
                filters,
            )

        if dataset == "parcels":
            from apps.farm_parcels.models import FarmParcel
            from apps.farm_parcels.views import FarmParcelListView

            view = FarmParcelListView()
            view.request = request
            rows = [
                [
                    parcel.farmer.record_id,
                    parcel.farmer.list_name,
                    parcel.area_hectares,
                    parcel.get_ownership_type_display(),
                    parcel.get_land_type_display(),
                    parcel.get_farm_type_display(),
                    "Active" if parcel.is_active else "Inactive",
                ]
                for parcel in view.get_queryset()
            ]
            filters = {
                "search": request.GET.get("q", ""),
                "barangay": request.GET.get("barangay", ""),
                "ownership": dict(FarmParcel.OWNERSHIP_CHOICES).get(
                    request.GET.get("ownership", ""), request.GET.get("ownership", "")
                ),
                "record_status": request.GET.get("status", "").title(),
                "area": {
                    "under1": "Below 1 ha",
                    "1to2": "1-2 ha",
                    "over2": "Above 2 ha",
                }.get(request.GET.get("area", ""), ""),
            }
            return (
                "Farm Parcel Management List",
                [
                    "Farmer ID",
                    "Farmer Name",
                    "Area (ha)",
                    "Ownership",
                    "Land Type",
                    "Farm Type",
                    "Status",
                ],
                rows,
                filters,
            )

        if dataset == "crops":
            from apps.crops.views import CropListView

            view = CropListView()
            view.request = request
            rows = [
                [
                    crop.parcel.farmer.record_id,
                    crop.parcel.farmer.list_name,
                    crop.crop_type,
                    crop.planting_date or "Not set",
                ]
                for crop in view.get_queryset()
            ]
            filters = {
                "search": request.GET.get("q", ""),
                "commodity": request.GET.get("crop_type", ""),
                "year": request.GET.get("year", ""),
                "record_view": request.GET.get("status", "").title() or "Current",
            }
            return (
                "Crop Management List",
                [
                    "Farmer ID",
                    "Farmer Name",
                    "Crop / Commodity",
                    "Planting Date",
                ],
                rows,
                filters,
            )

        if dataset == "requests":
            from apps.service_catalog.models import ServiceCatalog
            from apps.service_requests.models import ServiceRequest
            from apps.service_requests.views import ServiceRequestListView

            view = ServiceRequestListView()
            view.request = request
            rows = [
                [
                    item.request_id,
                    item.service.name,
                    item.farmer.record_id,
                    item.farmer.list_name,
                    item.farmer.barangay,
                    item.subject,
                    item.get_priority_display(),
                    item.get_status_display(),
                    timezone.localtime(item.created_at).strftime("%B %d, %Y %I:%M %p"),
                ]
                for item in view.get_queryset()
            ]
            service_id = request.GET.get("request_type", "")
            service_name = ""
            if service_id.isdigit():
                service_name = (
                    ServiceCatalog.objects.filter(pk=int(service_id))
                    .values_list("name", flat=True)
                    .first()
                    or ""
                )
            filters = {
                "search": request.GET.get("q", ""),
                "request_type": service_name,
                "status": dict(ServiceRequest.STATUS_CHOICES).get(
                    request.GET.get("status", ""), request.GET.get("status", "")
                ),
                "priority": dict(ServiceRequest.PRIORITY_CHOICES).get(
                    request.GET.get("priority", ""), request.GET.get("priority", "")
                ),
                "requested_date": request.GET.get("date", ""),
            }
            return (
                "Service Request Management List",
                [
                    "Request ID",
                    "Request Type",
                    "Farmer ID",
                    "Farmer Name",
                    "Barangay",
                    "Subject",
                    "Priority",
                    "Status",
                    "Date Requested",
                ],
                rows,
                filters,
            )

        raise ValueError("Choose a valid management table.")

    def get(self, request, dataset):
        try:
            title, headers, rows, filters = self._dataset(request, dataset)
            export_format = request.GET.get("format", "csv").lower()
            response = generate_table_export(
                title,
                headers,
                rows,
                export_format,
                filters,
            )
            record_request_event(
                request,
                title="Management Data Exported",
                module="Reports",
                description=f"{request.user.display_name} exported a filtered management table.",
                target_label=title,
                details=[
                    {"field": "Format", "after": export_format.upper()},
                    {"field": "Rows", "after": len(rows)},
                ],
            )
            return response
        except (ValueError, ImportError) as error:
            return HttpResponseBadRequest(str(error) or "The table export could not be generated.")
