from datetime import date

from django.contrib.auth import get_user_model
from django.http import HttpResponseBadRequest
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import RoleRequiredMixin, StaffRequiredMixin
from apps.common.constants import ROSARIO_BARANGAYS
from apps.crops.models import CropRecord
from apps.activity_logs.models import ActivityLog
from apps.activity_logs.services import record_request_event
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention
from apps.inventory.models import InventoryItem, InventoryMovement
from apps.service_requests.models import ServiceRequest
from .analytics import ANALYTICS_TABS, descriptive_analytics, report_metrics, report_preview
from .export import (
    COMMODITY_REPORT_KEYS,
    DATE_RANGES,
    REPORT_TEMPLATES,
    SYSTEM_REPORT_TEMPLATES,
    date_range_label,
    farmers_csv,
    generate_report,
    generate_system_report,
    generate_table_export,
    normalize_report_filters,
    resolve_date_range,
)


class ReportsAccessRequiredMixin(RoleRequiredMixin):
    denied_message = "Reports and analytics are available to authorized FMIS personnel only."

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_admin or user.role == "STAFF")


class ReportsView(FMISLoginRequiredMixin, ReportsAccessRequiredMixin, TemplateView):
    template_name = "reports/home.html"

    @staticmethod
    def _filters(source, report_type=""):
        return normalize_report_filters(report_type, {
            "year": source.get("year", ""),
            "barangay": source.get("barangay", ""),
            "commodity": source.get("commodity", ""),
            "status": source.get("status", ""),
            "intervention_type": source.get("intervention_type", ""),
            "role": source.get("role", ""),
            "account_status": source.get("account_status", ""),
            "module": source.get("module", ""),
            "staff": source.get("staff", ""),
            "association": source.get("association", ""),
        })

    @staticmethod
    def _active_filters(report_type, date_range, filters):
        active = [{"label": "Period", "value": date_range_label(date_range)}]
        for key, label in (
            ("year", "Year"),
            ("barangay", "Barangay"),
            ("commodity", "Commodity"),
            ("association", "Association"),
        ):
            if filters.get(key):
                active.append({"label": label, "value": filters[key]})
        if report_type == "service_effectiveness" and filters.get("status"):
            active.append(
                {
                    "label": "Status",
                    "value": dict(ServiceRequest.STATUS_CHOICES).get(
                        filters["status"], filters["status"]
                    ),
                }
            )
        if report_type in {"intervention_summary", "intervention_registry"} and filters.get(
            "intervention_type"
        ):
            active.append(
                {
                    "label": "Intervention Type",
                    "value": dict(Intervention.TYPE_CHOICES).get(
                        filters["intervention_type"], filters["intervention_type"]
                    ),
                }
            )
        return active

    def get_context_data(self, **kwargs):
        current_year = date.today().year
        source = kwargs.pop("form_data", self.request.GET)
        selected_report_type = source.get("report_type", "")
        filters = self._filters(source, selected_report_type)
        date_range_choice = source.get("date_range", "all")
        if date_range_choice not in DATE_RANGES:
            date_range_choice = "all"
        date_from = source.get("date_from", "")
        date_to = source.get("date_to", "")
        system_report = self.request.user.is_admin
        # Reports & Analytics opens on the descriptive overview. The report
        # builder remains available as an explicit Generate Reports tab.
        analytics_tab = source.get("analytics_tab", "overview")
        valid_analytics_tabs = {key for key, _label in ANALYTICS_TABS}
        if analytics_tab not in valid_analytics_tabs:
            analytics_tab = "overview"
        analytics_date_choice = source.get("analytics_date_range", "all")
        if analytics_date_choice not in DATE_RANGES:
            analytics_date_choice = "all"
        analytics_date_from = source.get("analytics_date_from", "")
        analytics_date_to = source.get("analytics_date_to", "")
        analytics_error = ""
        try:
            analytics_date_range = resolve_date_range(
                analytics_date_choice,
                analytics_date_from,
                analytics_date_to,
            )
        except ValueError as error:
            analytics_error = str(error)
            analytics_date_choice = "all"
            analytics_date_range = "all"
        analytics_filters = {
            "barangay": source.get("analytics_barangay", ""),
            "commodity": source.get("analytics_commodity", ""),
            "request_status": source.get("analytics_request_status", ""),
            "request_priority": source.get("analytics_request_priority", ""),
            "intervention_type": source.get("analytics_intervention_type", ""),
            "inventory_category": source.get("analytics_inventory_category", ""),
            "inventory_movement_type": source.get(
                "analytics_inventory_movement_type", ""
            ),
        }
        preview = None
        report_error = ""
        try:
            date_range = resolve_date_range(date_range_choice, date_from, date_to)
            if selected_report_type:
                preview = report_preview(
                    selected_report_type,
                    date_range,
                    filters,
                    system_report=system_report,
                )
        except ValueError as error:
            report_error = str(error)
            filters = {
                "year": "",
                "barangay": "",
                "commodity": "",
                "status": "",
                "intervention_type": "",
            }
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
            "request_priority_choices": ServiceRequest.PRIORITY_CHOICES,
            "intervention_type_choices": Intervention.TYPE_CHOICES,
            "inventory_category_choices": InventoryItem.CATEGORY_CHOICES,
            "inventory_movement_choices": InventoryMovement.MOVEMENT_CHOICES,
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
            "staff_choices": get_user_model().objects.filter(role="STAFF").order_by(
                "first_name", "last_name", "username"
            ),
            "association_choices": Farmer.objects.filter(
                is_active=True,
                is_association_member=True,
            ).exclude(fca_membership="").values_list(
                "fca_membership", flat=True
            ).distinct().order_by("fca_membership"),
            "selected_report_type": selected_report_type,
            "selected_date_range": date_range_choice,
            "selected_date_from": date_from,
            "selected_date_to": date_to,
            "selected_filters": filters,
            "active_report_filters": self._active_filters(
                selected_report_type, date_range, filters
            ) if selected_report_type else [],
            "commodity_report_types": COMMODITY_REPORT_KEYS,
            "report_preview": preview,
            "report_error": report_error,
            "analytics_tabs": ANALYTICS_TABS,
            "analytics_tab": analytics_tab,
            "analytics_date_ranges": DATE_RANGES,
            "selected_analytics_date_range": analytics_date_choice,
            "selected_analytics_date_from": analytics_date_from,
            "selected_analytics_date_to": analytics_date_to,
            "selected_analytics_filters": analytics_filters,
            "analytics_error": analytics_error,
        }
        # The report generator must remain independent from descriptive
        # analytics. Do not execute analytics queries while the user is on the
        # Generate Reports tab; a data-specific analytics failure must never
        # take the established report workflow offline.
        if analytics_tab != "reports":
            context["descriptive"] = descriptive_analytics(
                analytics_tab,
                analytics_date_range,
                analytics_filters,
            )
        return context

    def post(self, request, *args, **kwargs):
        try:
            generator = generate_system_report if request.user.is_admin else generate_report
            date_range = resolve_date_range(
                request.POST.get("date_range", ""),
                request.POST.get("date_from", ""),
                request.POST.get("date_to", ""),
            )
            response = generator(
                request.POST.get("report_type", ""),
                request.POST.get("format", ""),
                date_range,
                {
                    "year": request.POST.get("year", ""),
                    "barangay": request.POST.get("barangay", ""),
                    "commodity": request.POST.get("commodity", ""),
                    "status": request.POST.get("status", ""),
                    "intervention_type": request.POST.get("intervention_type", ""),
                    "role": request.POST.get("role", ""),
                    "account_status": request.POST.get("account_status", ""),
                    "module": request.POST.get("module", ""),
                    "staff": request.POST.get("staff", ""),
                    "association": request.POST.get("association", ""),
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
                    "Active" if farmer.is_active else "Inactive",
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
            farmers = list(view.get_queryset())
            rows = []
            for farmer in farmers:
                crops = [
                    crop
                    for parcel in farmer.listed_parcels
                    for crop in parcel.listed_crops
                ]
                rows.append([
                    farmer.record_id,
                    farmer.list_name,
                    ", ".join(dict.fromkeys(crop.crop_type for crop in crops)),
                    "Active" if max(crops, key=lambda crop: crop.pk).is_active else "Inactive",
                ])
            filters = {
                "search": request.GET.get("q", ""),
                "commodity": request.GET.get("crop_type", ""),
                "record_status": request.GET.get("status", "").title() or "Active",
            }
            return (
                "Commodity Management List",
                [
                    "Farmer ID",
                    "Farmer Name",
                    "Commodity",
                    "Status",
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
                    item.beneficiary_reference,
                    item.beneficiary_label,
                    (
                        item.target_barangay
                        if item.scope == "BARANGAY"
                        else (
                            item.target_association
                            if item.scope == "ASSOCIATION"
                            else (
                                "Walk-In"
                                if item.scope == "WALK_IN"
                                else item.farmer.barangay
                            )
                        )
                    ),
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
                    "Coverage",
                    "Name",
                    "Barangay",
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
