from django.contrib import messages
from django.db import transaction
from django.db.models import Case, IntegerField, Q, Value, When
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import AdminRequiredMixin, StaffRequiredMixin
from apps.activity_logs.services import record_request_event
from apps.common.record_history import service_request_rows
from apps.interventions.services import complete_registered_request_intervention
from .forms import ServiceLevelPolicyForm, ServiceRequestForm
from .models import ServiceLevelPolicy, ServiceRequest, ServiceRequestHistory
from .services import ensure_service_level_policies, recalculate_open_deadlines


def _history_value(field, value):
    if value in (None, ""):
        return "Not set"
    if field == "service":
        return value.name
    if field == "farmer":
        return value.list_name if value else "Not applicable"
    if field == "assigned_to":
        return value.display_name
    if field == "status":
        return dict(ServiceRequest.STATUS_CHOICES).get(value, value)
    if field == "priority":
        return dict(ServiceRequest.PRIORITY_CHOICES).get(value, value)
    if field == "scope":
        return dict(ServiceRequest.SCOPE_CHOICES).get(value, value)
    return str(value)


def _request_changes(before, after, changed_fields):
    labels = {
        "farmer": "Farmer",
        "scope": "Scope",
        "target_barangay": "Barangay",
        "service": "Request type",
        "subject": "Subject",
        "priority": "Priority",
        "status": "Status",
        "notes": "Request details",
        "assigned_to": "Assigned staff",
        "satisfaction_rating": "Farmer satisfaction",
        "satisfaction_feedback": "Farmer feedback",
        "feedback_method": "Feedback collection method",
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
    def get_queryset(self):
        queryset = ServiceRequest.objects.select_related("farmer", "service", "assigned_to")
        query = self.request.GET.get("q", "").strip()
        request_type = self.request.GET.get("request_type", "").strip()
        status = self.request.GET.get("status", "").strip()
        priority = self.request.GET.get("priority", "").strip()
        assigned_to = self.request.GET.get("assigned_to", "").strip()
        overdue = self.request.GET.get("overdue", "").strip()
        date_from = self.request.GET.get("date_from", "").strip()
        date_to = self.request.GET.get("date_to", "").strip()

        if query:
            request_id = query.upper().removeprefix("SR-")
            filters = (
                Q(subject__icontains=query)
                | Q(notes__icontains=query)
                | Q(service__name__icontains=query)
                | Q(farmer__first_name__icontains=query)
                | Q(farmer__last_name__icontains=query)
                | Q(target_barangay__icontains=query)
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
        if assigned_to.isdigit():
            queryset = queryset.filter(assigned_to_id=int(assigned_to))
        elif assigned_to == "unassigned":
            queryset = queryset.filter(assigned_to__isnull=True)
        now = timezone.now()
        overdue_filter = (
            Q(first_responded_at__isnull=True, first_response_due_at__lt=now)
            | Q(first_responded_at__isnull=False, due_at__lt=now)
        )
        if overdue == "yes":
            queryset = queryset.exclude(status__in=("COMPLETED", "CANCELLED")).filter(overdue_filter)
        elif overdue == "no":
            queryset = queryset.exclude(overdue_filter)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset.order_by("-created_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
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
        if form.cleaned_data.get("satisfaction_rating"):
            form.instance.feedback_recorded_by = self.request.user
        with transaction.atomic():
            response = super().form_valid(form)
            completed_intervention = None
            if self.object.status == "COMPLETED":
                completed_intervention = complete_registered_request_intervention(
                    self.object, self.request.user
                )
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
        if completed_intervention:
            record_request_event(
                self.request,
                title="Completed Intervention Created",
                module="Interventions",
                description=f"{self.request.user.display_name} completed a service request and recorded its intervention.",
                target_label=completed_intervention.reference_id,
            )
        if completed_intervention:
            messages.success(
                self.request,
                f"{self.object.request_id} and {completed_intervention.reference_id} were created as Completed.",
            )
        else:
            messages.success(
                self.request,
                f"{self.object.request_id} was created and added to the history log.",
            )
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
        context.update({"history_title": "Service Request History", "record_label": f"{self.object.request_id} · {self.object.service.name}", "back_url": reverse_lazy("service_requests:detail", args=[self.object.pk]), "edit_url": reverse_lazy("service_requests:edit", args=[self.object.pk]), "edit_label": "Edit Request", "history_entries": service_request_rows(self.object.history.all())})
        return context


class ServiceRequestUpdateView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareRequestMixin, UpdateView
):
    model = ServiceRequest
    form_class = ServiceRequestForm
    template_name = "service_requests/form.html"
    success_url = reverse_lazy("service_requests:list")

    def form_valid(self, form):
        before = ServiceRequest.objects.select_related(
            "farmer", "service", "assigned_to"
        ).get(pk=form.instance.pk)
        changed_fields = list(form.changed_data)
        if "satisfaction_rating" in changed_fields and form.cleaned_data.get("satisfaction_rating"):
            form.instance.feedback_recorded_by = self.request.user
        completed_intervention = None
        with transaction.atomic():
            response = super().form_valid(form)
            if self.object.status == "COMPLETED":
                completed_intervention = complete_registered_request_intervention(
                    self.object, self.request.user
                )
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
        if completed_intervention:
            record_request_event(
                self.request,
                title="Completed Intervention Recorded",
                module="Interventions",
                description=f"{self.request.user.display_name} completed a service request and recorded its intervention.",
                target_label=completed_intervention.reference_id,
            )
            messages.success(
                self.request,
                f"{self.object.request_id} and {completed_intervention.reference_id} were marked Completed.",
            )
        else:
            messages.success(self.request, f"{self.object.request_id} was updated and the change was recorded.")
        record_request_event(
            self.request,
            title="Service Request Updated",
            module="Service Requests",
            description=f"{self.request.user.display_name} updated a service request.",
            target_label=self.object.request_id,
        )
        return response


class ServiceLevelPolicyView(FMISLoginRequiredMixin, AdminRequiredMixin, View):
    template_name = "service_requests/service_levels.html"
    formset_class = modelformset_factory(
        ServiceLevelPolicy,
        form=ServiceLevelPolicyForm,
        extra=0,
    )

    @staticmethod
    def _queryset():
        return ServiceLevelPolicy.objects.annotate(
            priority_order=Case(
                When(priority="HIGH", then=Value(0)),
                When(priority="MEDIUM", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by("priority_order")

    def get(self, request):
        ensure_service_level_policies()
        formset = self.formset_class(queryset=self._queryset())
        return self._render(request, formset)

    def post(self, request):
        ensure_service_level_policies()
        formset = self.formset_class(request.POST, queryset=self._queryset())
        if formset.is_valid():
            with transaction.atomic():
                policies = formset.save(commit=False)
                for policy in policies:
                    policy.updated_by = request.user
                    policy.full_clean()
                    policy.save()
                recalculate_open_deadlines()
            record_request_event(
                request,
                title="Service Targets Updated",
                module="Settings",
                description=f"{request.user.display_name} updated the proposed service request targets.",
                target_label="Service request targets",
            )
            messages.success(request, "Service request targets were updated and open deadlines recalculated.")
            return redirect("service_requests:service_levels")
        return self._render(request, formset, status=400)

    def _render(self, request, formset, status=200):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"formset": formset, "base_template": "base/admin_base.html"},
            status=status,
        )


class ServiceRequestDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Retain the record and close it instead of permanently deleting it."""

    def post(self, request, pk):
        service_request = get_object_or_404(ServiceRequest, pk=pk)
        if service_request.status == "CANCELLED":
            if request.POST.get("action") != "restore":
                messages.info(request, f"{service_request.request_id} is already cancelled.")
                return redirect("service_requests:list")
            with transaction.atomic():
                service_request.status = "PENDING"
                service_request.updated_at = timezone.now()
                # Use the model transition hook so response/completion timing
                # remains consistent when a cancelled request is restored.
                service_request.save()
                ServiceRequestHistory.objects.create(
                    service_request=service_request,
                    actor=request.user,
                    action="REOPENED",
                    from_status="CANCELLED",
                    to_status="PENDING",
                    changes=[{"field": "Status", "before": "Cancelled", "after": "Pending"}],
                )
            record_request_event(
                request,
                title="Service Request Reopened",
                module="Service Requests",
                description=f"{request.user.display_name} reopened a cancelled service request.",
                target_label=service_request.request_id,
            )
            messages.success(request, f"{service_request.request_id} was restored as Pending.")
            return redirect("service_requests:list")
        previous_status = service_request.status
        with transaction.atomic():
            service_request.status = "CANCELLED"
            service_request.updated_at = timezone.now()
            service_request.save()
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
