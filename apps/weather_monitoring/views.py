from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.activity_logs.services import record_request_event
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin, RoleRequiredMixin
from .forms import WeatherCoverageAreaForm, WeatherEventReviewForm, WeatherMonitoringRuleForm
from .models import WeatherCoverageArea, WeatherMonitoringRule, WeatherMonitoringRun, WeatherRiskEvent
from .services import approve_event, dismiss_event


class WeatherUserRequiredMixin(RoleRequiredMixin):
    denied_message = "Weather monitoring is available to authorized FMIS staff only."

    def test_func(self):
        user = self.request.user
        return user.is_authenticated and (user.is_admin or user.role == "STAFF")


class WeatherEventListView(FMISLoginRequiredMixin, WeatherUserRequiredMixin, ListView):
    model = WeatherRiskEvent
    template_name = "weather_monitoring/event_list.html"
    paginate_by = 25

    def get_queryset(self):
        queryset = WeatherRiskEvent.objects.select_related("coverage_area", "rule", "assigned_to").annotate(
            parcel_count=Count("parcel_links", distinct=True)
        )
        status = self.request.GET.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = WeatherRiskEvent.STATUS_CHOICES
        context["last_run"] = WeatherMonitoringRun.objects.first()
        context["base_template"] = "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        return context


class WeatherEventDetailView(FMISLoginRequiredMixin, WeatherUserRequiredMixin, DetailView):
    model = WeatherRiskEvent
    template_name = "weather_monitoring/event_detail.html"

    def get_queryset(self):
        return WeatherRiskEvent.objects.select_related(
            "coverage_area", "rule", "reviewed_by", "assigned_to"
        ).prefetch_related("parcel_links__parcel__farmer", "request_links__service_request")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["review_form"] = WeatherEventReviewForm()
        context["base_template"] = "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        return context


class WeatherEventReviewView(FMISLoginRequiredMixin, WeatherUserRequiredMixin, View):
    def post(self, request, pk):
        event = get_object_or_404(WeatherRiskEvent, pk=pk)
        if event.status != WeatherRiskEvent.STATUS_DRAFT:
            messages.warning(request, "This weather event has already been reviewed.")
            return redirect("weather_monitoring:event_detail", pk=pk)
        form = WeatherEventReviewForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect("weather_monitoring:event_detail", pk=pk)
        if form.cleaned_data["action"] == "approve":
            approve_event(
                event,
                reviewer=request.user,
                assigned_to=form.cleaned_data["assigned_to"],
                scheduled_for=form.cleaned_data["scheduled_for"],
                reason=form.cleaned_data["reason"],
            )
            title = "Weather Event Approved"
            message = "The preliminary event was approved and linked service requests were created by barangay."
        else:
            dismiss_event(event, reviewer=request.user, reason=form.cleaned_data["reason"])
            title = "Weather Event Dismissed"
            message = "The preliminary event was dismissed; no service request was created."
        record_request_event(
            request,
            title=title,
            module="Service Requests",
            description=f"{request.user.display_name} reviewed a preliminary weather event.",
            target_label=event.event_id,
            reason=form.cleaned_data["reason"],
        )
        messages.success(request, message)
        return redirect("weather_monitoring:event_detail", pk=pk)


class WeatherSettingsMixin:
    template_name = "weather_monitoring/settings_form.html"
    success_url = reverse_lazy("weather_monitoring:settings")

    def form_valid(self, form):
        if isinstance(form.instance, WeatherMonitoringRule):
            form.instance.updated_by = self.request.user
        messages.success(self.request, "Weather monitoring configuration was saved.")
        return super().form_valid(form)


class WeatherSettingsView(FMISLoginRequiredMixin, AdminRequiredMixin, ListView):
    model = WeatherMonitoringRule
    template_name = "weather_monitoring/settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            coverage_areas=WeatherCoverageArea.objects.all(),
            license_reviewed=settings.FMIS_WEATHER_LICENSE_REVIEWED,
            scheduler_configured=settings.FMIS_WEATHER_SCHEDULER_CONFIGURED,
            last_run=WeatherMonitoringRun.objects.first(),
        )
        return context


class CoverageCreateView(WeatherSettingsMixin, FMISLoginRequiredMixin, AdminRequiredMixin, CreateView):
    form_class = WeatherCoverageAreaForm


class CoverageUpdateView(WeatherSettingsMixin, FMISLoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = WeatherCoverageArea
    form_class = WeatherCoverageAreaForm


class RuleCreateView(WeatherSettingsMixin, FMISLoginRequiredMixin, AdminRequiredMixin, CreateView):
    form_class = WeatherMonitoringRuleForm


class RuleUpdateView(WeatherSettingsMixin, FMISLoginRequiredMixin, AdminRequiredMixin, UpdateView):
    model = WeatherMonitoringRule
    form_class = WeatherMonitoringRuleForm
