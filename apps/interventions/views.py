from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.filters import parse_inclusive_date_range
from apps.common.permissions import StaffRequiredMixin
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest, ServiceRequestHistory

from .forms import InterventionForm
from .models import Intervention, InterventionRecipient
from .services import INTERVENTION_TYPE_BY_SERVICE_CODE


def _recipient_summary(intervention):
    recipients = (
        intervention.recipients.filter(is_active=True)
        .select_related("farmer")
        .order_by("farmer__last_name", "farmer__first_name", "farmer_id")
    )
    recipient_count = recipients.count()
    if not recipient_count:
        return "No farmers"
    visible_recipients = list(recipients[:10])
    visible = ", ".join(
        f"{recipient.farmer.record_id} {recipient.farmer.list_name}"
        for recipient in visible_recipients
    )
    remaining = recipient_count - len(visible_recipients)
    return f"{recipient_count} farmer(s): {visible}" + (
        f" (+{remaining} more)" if remaining else ""
    )


def _intervention_snapshot(intervention):
    not_set = "Not set"
    return {
        "Coverage": dict(Intervention.SCOPE_CHOICES).get(
            intervention.scope, intervention.scope
        ),
        "Barangay": intervention.target_barangay or not_set,
        "Recipients": _recipient_summary(intervention),
        "Related service request": (
            intervention.service_request.request_id
            if intervention.service_request_id
            else "Not linked"
        ),
        "Status": dict(Intervention.STATUS_CHOICES).get(
            intervention.status, intervention.status
        ),
        "Intervention type": dict(Intervention.TYPE_CHOICES).get(
            intervention.intervention_type, intervention.intervention_type
        ),
        "Intervention date": (
            intervention.intervention_date.strftime("%b %d, %Y")
            if intervention.intervention_date
            else not_set
        ),
        "Quantity": str(intervention.quantity) if intervention.quantity is not None else not_set,
        "Unit": intervention.unit or not_set,
        "Description": intervention.description or not_set,
        "Provider": intervention.provider or not_set,
    }


def _intervention_changes(before, after):
    return [
        {"field": field, "before": before.get(field, "Not set"), "after": value}
        for field, value in after.items()
        if before.get(field, "Not set") != value
    ]


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


def _sync_linked_request_status(intervention, actor):
    """Keep an open service request aligned with its delivered intervention."""
    linked_request = intervention.service_request
    if not linked_request:
        return
    previous_status = linked_request.status
    if intervention.status == "COMPLETED":
        next_status = "COMPLETED"
        status_note = "Completed after the linked intervention was completed"
    elif intervention.status in {"DRAFT", "SCHEDULED", "ONGOING"} and previous_status == "PENDING":
        next_status = "IN_PROGRESS"
        status_note = "In Progress after an intervention was linked"
    else:
        return
    if previous_status == next_status:
        return
    linked_request.status = next_status
    linked_request.save(update_fields=["status", "updated_at"])
    ServiceRequestHistory.objects.create(
        service_request=linked_request,
        actor=actor,
        action="UPDATED",
        from_status=previous_status,
        to_status=next_status,
        changes=[
            {
                "field": "Status",
                "before": dict(ServiceRequest.STATUS_CHOICES).get(
                    previous_status, previous_status
                ),
                "after": status_note,
            }
        ],
    )


class InterventionAccessMixin(FMISLoginRequiredMixin, StaffRequiredMixin):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        )
        return context


class InterventionFarmerSearchView(InterventionAccessMixin, View):
    def get(self, request):
        query = request.GET.get("q", "").strip()
        farmers = Farmer.objects.filter(is_active=True)
        if query:
            filters = (
                Q(first_name__icontains=query)
                | Q(middle_name__icontains=query)
                | Q(last_name__icontains=query)
                | Q(rsbsa_number__icontains=query)
                | Q(barangay__icontains=query)
            )
            record_number = query.upper().removeprefix("F-")
            if record_number.isdigit():
                filters |= Q(pk=int(record_number))
            farmers = farmers.filter(filters)
        farmers = farmers.order_by("last_name", "first_name", "pk")[:30]
        return JsonResponse(
            {
                "results": [
                    {
                        "id": farmer.pk,
                        "label": (
                            f"{farmer.record_id}"
                            f"{' / RSBSA ' + farmer.rsbsa_number if farmer.rsbsa_number else ''}"
                            f" - {farmer.list_name} ({farmer.barangay})"
                        ),
                    }
                    for farmer in farmers
                ]
            }
        )


class InterventionListView(InterventionAccessMixin, ListView):
    model = Intervention
    template_name = "interventions/list.html"
    def get_queryset(self):
        queryset = (
            Intervention.objects.select_related("farmer", "service_request", "recorded_by")
            .annotate(
                beneficiary_count=Count(
                    "recipients", filter=Q(recipients__is_active=True), distinct=True
                )
            )
        )
        query = self.request.GET.get("q", "").strip()
        kind = self.request.GET.get("type", "").strip()
        status = self.request.GET.get("status", "")
        barangay = self.request.GET.get("barangay", "").strip()
        date_range = parse_inclusive_date_range(self.request.GET, label="intervention")
        self.filter_date_error = date_range.error
        if query:
            filters = Q(description__icontains=query) | Q(farmer__first_name__icontains=query) | Q(farmer__last_name__icontains=query) | Q(farmer__rsbsa_number__icontains=query) | Q(recipients__farmer__first_name__icontains=query) | Q(recipients__farmer__last_name__icontains=query) | Q(recipients__farmer__rsbsa_number__icontains=query) | Q(target_barangay__icontains=query)
            reference = query.upper().removeprefix("INT-")
            if reference.isdigit():
                filters |= Q(pk=int(reference))
            queryset = queryset.filter(filters).distinct()
        if kind:
            queryset = queryset.filter(intervention_type=kind)
        if status == "archived":
            queryset = queryset.filter(is_active=False)
        else:
            queryset = queryset.filter(is_active=True)
            valid_statuses = {value for value, _label in Intervention.STATUS_CHOICES}
            if status in valid_statuses:
                queryset = queryset.filter(status=status)
        if barangay:
            queryset = queryset.filter(
                Q(target_barangay=barangay)
                | Q(farmer__barangay=barangay)
                | Q(recipients__farmer__barangay=barangay)
            ).distinct()
        if not date_range.error:
            if date_range.start:
                queryset = queryset.filter(intervention_date__gte=date_range.start)
            if date_range.end:
                queryset = queryset.filter(intervention_date__lte=date_range.end)
        return queryset.order_by("-intervention_date", "-created_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type_choices"] = Intervention.TYPE_CHOICES
        context["status_choices"] = Intervention.STATUS_CHOICES
        context["barangays"] = (
            Farmer.objects.values_list("barangay", flat=True).distinct().order_by("barangay")
        )
        context["filter_date_error"] = getattr(self, "filter_date_error", "")
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
            if service_request.status not in {"PENDING", "IN_PROGRESS"}:
                messages.error(
                    request,
                    "Only a Pending or In Progress service request can proceed to an intervention.",
                )
                return redirect("service_requests:detail", pk=service_request.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        request_id = self.request.GET.get("service_request", "").strip()
        if request_id.isdigit():
            service_request = ServiceRequest.objects.filter(
                pk=int(request_id), status__in=("PENDING", "IN_PROGRESS")
            ).select_related("service", "farmer").first()
            if service_request:
                initial.update(
                    {
                        "scope": service_request.scope,
                        "service_request": service_request,
                        "farmer": service_request.farmer,
                        "target_barangay": service_request.target_barangay,
                        "intervention_type": INTERVENTION_TYPE_BY_SERVICE_CODE.get(
                            service_request.service.code,
                            "OTHER",
                        ),
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
        with transaction.atomic():
            response = super().form_valid(form)
            recipient_ids = _resolved_recipient_ids(form)
            _sync_recipients(self.object, recipient_ids)
            _sync_linked_request_status(self.object, self.request.user)
            created_values = _intervention_snapshot(self.object)
            record_request_event(
                self.request,
                title="Intervention Recorded",
                module="Interventions",
                description=f"{self.request.user.display_name} recorded assistance for {len(recipient_ids)} farmer(s).",
                target_label=self.object.reference_id,
                details=_intervention_changes({}, created_values),
            )
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
        ).prefetch_related(
            Prefetch("recipients", queryset=active_recipients, to_attr="active_recipients"),
            "inventory_movements__item",
            "inventory_movements__recorded_by",
        )


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
        before = Intervention.objects.select_related("service_request").get(
            pk=form.instance.pk
        )
        before_values = _intervention_snapshot(before)
        form.instance.recorded_by = self.request.user
        scope = form.cleaned_data["scope"]
        form.instance.farmer = form.cleaned_data.get("farmer") if scope == "INDIVIDUAL" else None
        form.instance.target_barangay = form.cleaned_data.get("target_barangay", "") if scope == "BARANGAY" else ""
        with transaction.atomic():
            response = super().form_valid(form)
            recipient_ids = _resolved_recipient_ids(form)
            _sync_recipients(self.object, recipient_ids)
            _sync_linked_request_status(self.object, self.request.user)
            after_values = _intervention_snapshot(self.object)
            record_request_event(
                self.request,
                title="Intervention Updated",
                module="Interventions",
                description=f"{self.request.user.display_name} updated an intervention for {len(recipient_ids)} farmer(s).",
                target_label=self.object.reference_id,
                details=_intervention_changes(before_values, after_values),
            )
        messages.success(self.request, f"{self.object.reference_id} was updated.")
        return response


class InterventionArchiveView(InterventionAccessMixin, View):
    def post(self, request, pk):
        intervention = get_object_or_404(Intervention, pk=pk)
        previous_state = "Active" if intervention.is_active else "Archived"
        restoring = request.POST.get("action") == "restore"
        intervention.is_active = restoring
        intervention.recorded_by = request.user
        intervention.save(update_fields=["is_active", "recorded_by", "updated_at"])
        action = "restored" if restoring else "archived"
        record_request_event(
            request,
            title=f"Intervention {action.title()}",
            module="Interventions",
            description=f"{request.user.display_name} {action} an intervention record.",
            target_label=intervention.reference_id,
            details=[
                {
                    "field": "Record status",
                    "before": previous_state,
                    "after": "Active" if restoring else "Archived",
                }
            ],
        )
        messages.success(request, f"{intervention.reference_id} was {action}.")
        return redirect("interventions:list")
