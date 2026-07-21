from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from .services import dashboard_metrics, staff_dashboard_metrics


class DashboardLandingView(FMISLoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return redirect("dashboard:admin_home" if request.user.is_admin else "dashboard:staff_home")


class AdminDashboardView(FMISLoginRequiredMixin, AdminRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(dashboard_metrics())
        return context


class StaffDashboardView(FMISLoginRequiredMixin, StaffRequiredMixin, TemplateView):
    template_name = "dashboard/staff_home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(staff_dashboard_metrics())
        return context
