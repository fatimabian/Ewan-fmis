from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest, ServiceRequestHistory

from .forms import InterventionForm
from .models import Intervention, InterventionRecipient


def _resolved_recipient_ids(form):
    scope = form.cleaned_data["scope"]
    if scope == "INDIVIDUAL":
        return [form.cleaned_data["farmer"].pk]
    if scope == "SELECTED":
        return list(form.cleaned_data["selected_farmers"].values_list("pk", flat=True))
    queryset = Farmer.objects.filter(is_active=True)
    if scope == "BARANGAY":
        queryset = queryset.filter(barangay=form.cleaned_data["target_barangay"])
    return list(queryset.values_list("pk", flat=True))


def _sync_recipients(intervention, farmer_ids):
    """Persist a fixed recipient snapshot using a constant number of database queries."""
    farmer_ids = list(dict.fromkeys(farmer_ids))
    default_status = "RECEIVED" if intervention.status == "COMPLETED" else "PENDING"
    existing_ids = set(
        intervention.recipients.filter(farmer_id__in=farmer_ids).values_list(
            "farmer_id", flat=True
        )
    )
    intervention.recipients.exclude(farmer_id__in=farmer_ids).update(is_active=False)
    intervention.recipients.filter(farmer_id__in=farmer_ids).update(is_active=True)
    if default_status == "RECEIVED":
        intervention.recipients.filter(
            farmer_id__in=farmer_ids, status="PENDING"
        ).update(status="RECEIVED", received_at=intervention.intervention_date)
    InterventionRecipient.objects.bulk_create(
        [
            InterventionRecipient(
                intervention=intervention,
                farmer_id=farmer_id,
                status=default_status,
                received_at=(intervention.intervention_date if default_status == "RECEIVED" else None),
            )
            for farmer_id in farmer_ids
            if farmer_id not in existing_ids
        ],
        ignore_conflicts=True,
    )


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
        queryset = (
            Intervention.objects.select_related("farmer", "service_request", "recorded_by")
            .prefetch_related("recipients__farmer")
            .annotate(beneficiary_count=Count("recipients", filter=Q(recipients__is_active=True)))
        )
        query = self.request.GET.get("q", "").strip()
        kind = self.request.GET.get("type", "").strip()
        status = self.request.GET.get("status", "active")
        if query:
            filters = Q(description__icontains=query) | Q(farmer__first_name__icontains=query) | Q(farmer__last_name__icontains=query) | Q(farmer__rsbsa_number__icontains=query) | Q(recipients__farmer__first_name__icontains=query) | Q(recipients__farmer__last_name__icontains=query) | Q(recipients__farmer__rsbsa_number__icontains=query) | Q(target_barangay__icontains=query)
            reference = query.upper().removeprefix("INT-")
            if reference.isdigit():
                filters |= Q(pk=int(reference))
            queryset = queryset.filter(filters).distinct()
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
                        "scope": "INDIVIDUAL",
                        "service_request": service_request,
                        "farmer": service_request.farmer,
                    }
                )
        return initial

    def form_valid(self, form):
        form.instance.recorded_by = self.request.user
        scope = form.cleaned_data["scope"]
        form.instance.farmer = form.cleaned_data.get("farmer") if scope == "INDIVIDUAL" else None
        form.instance.target_barangay = (
            form.cleaned_data.get("target_barangay", "") if scope == "BARANGAY" else ""
        )
        linked_request = form.cleaned_data.get("service_request")
        with transaction.atomic():
            response = super().form_valid(form)
            recipient_ids = _resolved_recipient_ids(form)
            _sync_recipients(self.object, recipient_ids)
            if linked_request and self.object.status == "COMPLETED":
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
            record_request_event(self.request, title="Intervention Recorded", module="Interventions", description=f"{self.request.user.display_name} recorded assistance for {len(recipient_ids)} farmer(s).", target_label=self.object.reference_id)
        if self.object.service_request:
            messages.success(
                self.request,
                f"{self.object.reference_id} was recorded and linked to {self.object.service_request.request_id}.",
            )
        else:
            messages.success(self.request, f"{self.object.reference_id} was saved for {len(recipient_ids)} farmer(s).")
        return response


class InterventionDetailView(InterventionAccessMixin, DetailView):
    model = Intervention
    template_name = "interventions/detail.html"

    def get_queryset(self):
        active_recipients = InterventionRecipient.objects.filter(is_active=True).select_related("farmer")
        return Intervention.objects.select_related(
            "farmer", "service_request", "recorded_by"
        ).prefetch_related(Prefetch("recipients", queryset=active_recipients, to_attr="active_recipients"))


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
        scope = form.cleaned_data["scope"]
        form.instance.farmer = form.cleaned_data.get("farmer") if scope == "INDIVIDUAL" else None
        form.instance.target_barangay = form.cleaned_data.get("target_barangay", "") if scope == "BARANGAY" else ""
        with transaction.atomic():
            response = super().form_valid(form)
            recipient_ids = _resolved_recipient_ids(form)
            _sync_recipients(self.object, recipient_ids)
            record_request_event(self.request, title="Intervention Updated", module="Interventions", description=f"{self.request.user.display_name} updated an intervention for {len(recipient_ids)} farmer(s).", target_label=self.object.reference_id)
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
