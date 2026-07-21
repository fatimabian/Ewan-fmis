from django.db.models import Q
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.service_catalog.models import ServiceCatalog
from .forms import ServiceRequestForm
from .models import ServiceRequest


class RoleAwareRequestMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        return context


class ServiceRequestListView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, ListView):
    model = ServiceRequest
    template_name = "service_requests/list.html"
    paginate_by = 10

    def get_queryset(self):
        queryset = ServiceRequest.objects.select_related("farmer", "service", "assigned_to")
        query = self.request.GET.get("q", "").strip()
        request_type = self.request.GET.get("request_type", "").strip()
        status = self.request.GET.get("status", "").strip()
        priority = self.request.GET.get("priority", "").strip()
        requested_date = self.request.GET.get("date", "").strip()

        if query:
            request_id = query.upper().removeprefix("SR-")
            filters = (
                Q(subject__icontains=query)
                | Q(notes__icontains=query)
                | Q(service__name__icontains=query)
                | Q(farmer__first_name__icontains=query)
                | Q(farmer__last_name__icontains=query)
            )
            if request_id.isdigit():
                filters |= Q(pk=int(request_id))
            farmer_id = query.upper().removeprefix("F-")
            if farmer_id.isdigit():
                filters |= Q(farmer_id=int(farmer_id))
            filters |= Q(farmer__rsbsa_number__icontains=query) | Q(farmer__barangay__icontains=query)
            queryset = queryset.filter(filters)
        if request_type.isdigit():
            queryset = queryset.filter(service_id=int(request_type))
        if status:
            queryset = queryset.filter(status=status)
        if priority:
            queryset = queryset.filter(priority=priority)
        if requested_date:
            queryset = queryset.filter(created_at__date=requested_date)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["request_types"] = ServiceCatalog.objects.filter(is_active=True).order_by("name")
        context["status_choices"] = ServiceRequest.STATUS_CHOICES
        context["priority_choices"] = ServiceRequest.PRIORITY_CHOICES
        return context


class ServiceRequestCreateView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, CreateView):
    form_class = ServiceRequestForm
    template_name = "service_requests/form.html"
    success_url = reverse_lazy("service_requests:list")


class ServiceRequestDetailView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, DetailView):
    model = ServiceRequest
    template_name = "service_requests/detail.html"


class ServiceRequestUpdateView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, UpdateView):
    model = ServiceRequest
    form_class = ServiceRequestForm
    template_name = "service_requests/form.html"
    success_url = reverse_lazy("service_requests:list")


class ServiceRequestDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, DeleteView):
    model = ServiceRequest
    success_url = reverse_lazy("service_requests:list")
