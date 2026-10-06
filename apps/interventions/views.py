from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.service_requests.models import ServiceRequest, ServiceRequestHistory

from .forms import InterventionForm
from .models import Intervention


class InterventionAccessMixin(FMISLoginRequiredMixin, StaffRequiredMixin):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        )
        return context


class InterventionListView(InterventionAccessMixin, ListView):
    model = Intervention
    template_name = "interventions/list.html"
    paginate_by = 10

    def get_queryset(self):
        queryset = Intervention.objects.select_related("farmer", "service_request", "recorded_by")
        query = self.request.GET.get("q", "").strip()
        kind = self.request.GET.get("type", "").strip()
        status = self.request.GET.get("status", "active")
        if query:
            filters = Q(description__icontains=query) | Q(farmer__first_name__icontains=query) | Q(farmer__last_name__icontains=query) | Q(farmer__rsbsa_number__icontains=query)
            reference = query.upper().removeprefix("INT-")
            if reference.isdigit():
                filters |= Q(pk=int(reference))
            queryset = queryset.filter(filters)
        if kind:
            queryset = queryset.filter(intervention_type=kind)
        if status != "all":
            queryset = queryset.filter(is_active=status != "archived")
        return queryset.order_by("pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type_choices"] = Intervention.TYPE_CHOICES
        return context


class InterventionCreateView(InterventionAccessMixin, CreateView):
    model = Intervention
    form_class = InterventionForm
    template_name = "interventions/form.html"

    success_url = reverse_lazy("interventions:list")

    def dispatch(self, request, *args, **kwargs):
        request_id = request.GET.get("service_request", "").strip()
        if request_id.isdigit():
            service_request = get_object_or_404(ServiceRequest, pk=int(request_id))
            if service_request.status != "IN_PROGRESS":
                messages.error(
                    request,
                    "Only an In Progress service request can proceed to an intervention.",
                )
                return redirect("service_requests:detail", pk=service_request.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        request_id = self.request.GET.get("service_request", "").strip()
        if request_id.isdigit():
            service_request = ServiceRequest.objects.filter(
                pk=int(request_id), status="IN_PROGRESS"
            ).first()
            if service_request:
                initial.update(
                    {
                        "service_request": service_request,
                        "farmer": service_request.farmer,
                    }
                )
        return initial

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        linked_request = form.cleaned_data.get("service_request")
        with transaction.atomic():
            response = super().form_valid(form)
            if linked_request:
                previous_status = linked_request.status
                linked_request.status = "COMPLETED"
                linked_request.save(update_fields=["status", "updated_at"])
                ServiceRequestHistory.objects.create(
                    service_request=linked_request,
                    actor=self.request.user,
                    action="UPDATED",
                    from_status=previous_status,
                    to_status="COMPLETED",
                    changes=[
                        {
                            "field": "Status",
                            "before": "In Progress",
                            "after": "Completed after intervention was recorded",
                        }
                    ],
                )
            record_request_event(self.request, title="Intervention Recorded", module="Interventions", description=f"{self.request.user.display_name} recorded assistance delivered to a farmer.", target_label=self.object.reference_id)
        if self.object.service_request:
            messages.success(
                self.request,
                f"{self.object.reference_id} was recorded and linked to {self.object.service_request.request_id}.",
            )
        else:
            messages.success(self.request, f"{self.object.reference_id} was recorded.")
        return response


class InterventionDetailView(InterventionAccessMixin, DetailView):
    model = Intervention
    template_name = "interventions/detail.html"

    def get_queryset(self):
        return Intervention.objects.select_related("farmer", "service_request", "recorded_by")


class InterventionHistoryView(InterventionAccessMixin, DetailView):
    model = Intervention
    template_name = "shared/record_history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        entries = ActivityLog.objects.filter(module="Interventions", target_label=self.object.reference_id).select_related("actor")
        context.update({"history_title": "Intervention Update History", "record_label": f"{self.object.reference_id} · {self.object.get_intervention_type_display()}", "back_url": reverse_lazy("interventions:detail", args=[self.object.pk]), "edit_url": reverse_lazy("interventions:edit", args=[self.object.pk]), "edit_label": "Edit Intervention", "history_entries": activity_rows(entries)})
        return context


class InterventionUpdateView(InterventionAccessMixin, UpdateView):
    model = Intervention
    form_class = InterventionForm
    template_name = "interventions/form.html"

    success_url = reverse_lazy("interventions:list")

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        response = super().form_valid(form)
        record_request_event(self.request, title="Intervention Updated", module="Interventions", description=f"{self.request.user.display_name} updated an intervention record.", target_label=self.object.reference_id)
        messages.success(self.request, f"{self.object.reference_id} was updated.")
        return response


class InterventionArchiveView(InterventionAccessMixin, View):
    def post(self, request, pk):
        intervention = get_object_or_404(Intervention, pk=pk)
        restoring = request.POST.get("action") == "restore"
        intervention.is_active = restoring
        intervention.recorded_by = request.user
        intervention.save(update_fields=["is_active", "recorded_by", "updated_at"])
        action = "restored" if restoring else "archived"
        record_request_event(request, title=f"Intervention {action.title()}", module="Interventions", description=f"{request.user.display_name} {action} an intervention record.", target_label=intervention.reference_id)
        messages.success(request, f"{intervention.reference_id} was {action}.")
        return redirect("interventions:list")
