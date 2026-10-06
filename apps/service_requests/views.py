from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.activity_logs.services import record_request_event
from apps.common.record_history import service_request_rows
from apps.service_catalog.models import ServiceCatalog
from .forms import ServiceRequestForm
from .models import ServiceRequest, ServiceRequestHistory


def _history_value(field, value):
    if value in (None, ""):
        return "Not set"
    if field == "service":
        return value.name
    if field == "farmer":
        return value.list_name
    if field == "assigned_to":
        return value.display_name
    if field == "status":
        return dict(ServiceRequest.STATUS_CHOICES).get(value, value)
    if field == "priority":
        return dict(ServiceRequest.PRIORITY_CHOICES).get(value, value)
    return str(value)


def _request_changes(before, after, changed_fields):
    labels = {
        "farmer": "Farmer",
        "service": "Request type",
        "subject": "Subject",
        "priority": "Priority",
        "status": "Status",
        "notes": "Request details",
        "assigned_to": "Assigned staff",
    }
    return [
        {
            "field": labels.get(field, field.replace("_", " ").title()),
            "before": _history_value(field, getattr(before, field)),
            "after": _history_value(field, getattr(after, field)),
        }
        for field in changed_fields
        if field in labels
        and _history_value(field, getattr(before, field))
        != _history_value(field, getattr(after, field))
    ]


class RoleAwareRequestMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        )
        return context


class ServiceRequestListView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, ListView
):
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
            filters |= Q(farmer__rsbsa_number__icontains=query) | Q(
                farmer__barangay__icontains=query
            )
            queryset = queryset.filter(filters)
        if request_type.isdigit():
            queryset = queryset.filter(service_id=int(request_type))
        if status:
            queryset = queryset.filter(status=status)
        else:
            # Completed requests become linked intervention records. Keep them
            # available through the explicit Completed filter without mixing
            # them into the active operational queue.
            queryset = queryset.exclude(status="COMPLETED")
        if priority:
            queryset = queryset.filter(priority=priority)
        if requested_date:
            queryset = queryset.filter(created_at__date=requested_date)
        return queryset.order_by("pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["request_types"] = ServiceCatalog.objects.filter(is_active=True).order_by("name")
        context["status_choices"] = ServiceRequest.STATUS_CHOICES
        context["priority_choices"] = ServiceRequest.PRIORITY_CHOICES
        return context


class ServiceRequestCreateView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, CreateView
):
    form_class = ServiceRequestForm
    template_name = "service_requests/form.html"
    success_url = reverse_lazy("service_requests:list")

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
            ServiceRequestHistory.objects.create(
                service_request=self.object,
                actor=self.request.user,
                action="CREATED",
                to_status=self.object.status,
                changes=[
                    {
                        "field": "Request",
                        "before": "Not created",
                        "after": self.object.subject,
                    }
                ],
            )
        messages.success(self.request, f"{self.object.request_id} was created and added to the history log.")
        record_request_event(
            self.request,
            title="Service Request Created",
            module="Service Requests",
            description=f"{self.request.user.display_name} created a service request.",
            target_label=self.object.request_id,
        )
        return response


class ServiceRequestDetailView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, DetailView
):
    model = ServiceRequest
    template_name = "service_requests/detail.html"

    def get_queryset(self):
        return ServiceRequest.objects.select_related(
            "farmer", "service", "assigned_to"
        ).prefetch_related("history__actor", "interventions__recorded_by")


class ServiceRequestHistoryView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, DetailView
):
    model = ServiceRequest
    template_name = "shared/record_history.html"

    def get_queryset(self):
        return ServiceRequest.objects.select_related("farmer", "service").prefetch_related("history__actor")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"history_title": "Service Request History", "record_label": f"{self.object.request_id} · {self.object.subject}", "back_url": reverse_lazy("service_requests:detail", args=[self.object.pk]), "edit_url": reverse_lazy("service_requests:edit", args=[self.object.pk]) if self.object.status != "CANCELLED" else "", "edit_label": "Edit Request", "history_entries": service_request_rows(self.object.history.all())})
        return context


class ServiceRequestUpdateView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, UpdateView
):
    model = ServiceRequest
    form_class = ServiceRequestForm
    template_name = "service_requests/form.html"
    success_url = reverse_lazy("service_requests:list")

    def dispatch(self, request, *args, **kwargs):
        service_request = get_object_or_404(ServiceRequest, pk=kwargs["pk"])
        if service_request.status == "CANCELLED":
            messages.info(
                request,
                f"{service_request.request_id} is cancelled and can no longer be changed.",
            )
            return redirect("service_requests:detail", pk=service_request.pk)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        before = ServiceRequest.objects.select_related(
            "farmer", "service", "assigned_to"
        ).get(pk=form.instance.pk)
        changed_fields = list(form.changed_data)
        with transaction.atomic():
            response = super().form_valid(form)
            action = (
                "REOPENED"
                if before.status == "CANCELLED" and self.object.status != "CANCELLED"
                else "UPDATED"
            )
            ServiceRequestHistory.objects.create(
                service_request=self.object,
                actor=self.request.user,
                action=action,
                from_status=before.status,
                to_status=self.object.status,
                changes=_request_changes(before, self.object, changed_fields),
            )
        messages.success(self.request, f"{self.object.request_id} was updated and the change was recorded.")
        record_request_event(
            self.request,
            title="Service Request Updated",
            module="Service Requests",
            description=f"{self.request.user.display_name} updated a service request.",
            target_label=self.object.request_id,
        )
        return response


class ServiceRequestDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Retain the record and close it instead of permanently deleting it."""

    def post(self, request, pk):
        service_request = get_object_or_404(ServiceRequest, pk=pk)
        if service_request.status == "CANCELLED":
            messages.info(request, f"{service_request.request_id} is already cancelled.")
            return redirect("service_requests:list")
        previous_status = service_request.status
        with transaction.atomic():
            service_request.status = "CANCELLED"
            service_request.updated_at = timezone.now()
            service_request.save(update_fields=["status", "updated_at"])
            ServiceRequestHistory.objects.create(
                service_request=service_request,
                actor=request.user,
                action="CANCELLED",
                from_status=previous_status,
                to_status="CANCELLED",
                changes=[
                    {
                        "field": "Status",
                        "before": dict(ServiceRequest.STATUS_CHOICES).get(previous_status, previous_status),
                        "after": "Cancelled",
                    }
                ],
            )
        record_request_event(
            request,
            title="Service Request Cancelled",
            module="Service Requests",
            description=f"{request.user.display_name} cancelled a service request without deleting it.",
            target_label=service_request.request_id,
        )
        messages.success(request, f"{service_request.request_id} was cancelled. Its history was preserved.")
        return redirect("service_requests:list")
