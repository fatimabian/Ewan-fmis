from datetime import date

from django.views import View
from django.views.generic import TemplateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.constants import ROSARIO_BARANGAYS
from apps.crops.models import CropRecord
from apps.service_requests.models import ServiceRequest
from .analytics import report_metrics, report_preview
from .export import DATE_RANGES, REPORT_TEMPLATES, build_report, farmers_csv, generate_report


class ReportsView(FMISLoginRequiredMixin, TemplateView):
    template_name = "reports/home.html"

    @staticmethod
    def _filters(source):
        return {
            "year": source.get("year", ""),
            "barangay": source.get("barangay", ""),
            "commodity": source.get("commodity", ""),
            "status": source.get("status", ""),
        }

    def get_context_data(self, **kwargs):
        current_year = date.today().year
        source = kwargs.pop("form_data", self.request.GET)
        filters = self._filters(source)
        date_range = source.get("date_range", "all")
        if date_range not in DATE_RANGES:
            date_range = "all"
        selected_report_type = source.get("report_type", "")
        preview = None
        report_error = ""
        try:
            if selected_report_type:
                preview = report_preview(selected_report_type, date_range, filters)
            else:
                build_report("farmer_master", date_range, filters)
        except ValueError as error:
            report_error = str(error)
            filters = {"year": "", "barangay": "", "commodity": "", "status": ""}
            date_range = "all"
        context = {
            **super().get_context_data(**kwargs),
            **report_metrics(date_range, filters),
            "base_template": "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html",
            "report_templates": REPORT_TEMPLATES,
            "date_ranges": DATE_RANGES,
            "report_years": range(current_year, current_year - 11, -1),
            "barangays": ROSARIO_BARANGAYS,
            "commodities": CropRecord.objects.exclude(crop_type="").values_list("crop_type", flat=True).distinct().order_by("crop_type"),
            "status_choices": ServiceRequest.STATUS_CHOICES,
            "selected_report_type": selected_report_type,
            "selected_date_range": date_range,
            "selected_filters": filters,
            "report_preview": preview,
            "report_error": report_error,
        }
        return context

    def post(self, request, *args, **kwargs):
        try:
            return generate_report(
                request.POST.get("report_type", ""),
                request.POST.get("format", ""),
                request.POST.get("date_range", ""),
                {
                    "year": request.POST.get("year", ""),
                    "barangay": request.POST.get("barangay", ""),
                    "commodity": request.POST.get("commodity", ""),
                    "status": request.POST.get("status", ""),
                },
            )
        except (ValueError, ImportError) as error:
            context = self.get_context_data(form_data=request.POST)
            context["report_error"] = str(error) or "The report could not be generated."
            return self.render_to_response(context, status=400)


class FarmerExportView(FMISLoginRequiredMixin, View):
    def get(self, request):
        return farmers_csv()
