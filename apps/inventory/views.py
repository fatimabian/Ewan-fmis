from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from apps.activity_logs.services import record_request_event
from apps.common.filters import parse_inclusive_date_range
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.interventions.services import ensure_inventory_release_intervention

from .forms import InventoryItemForm, InventoryMovementForm
from .models import InventoryItem, InventoryMovement
from .services import record_inventory_movement


class InventoryAccessMixin(FMISLoginRequiredMixin, StaffRequiredMixin):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = "base/staff_base.html"
        return context


class InventoryListView(InventoryAccessMixin, ListView):
    template_name = "inventory/list.html"
    paginate_by = 25

    def get_queryset(self):
        self.tab = self.request.GET.get("tab", "items")
        if self.tab not in {"items", "movements"}:
            self.tab = "items"
        query = self.request.GET.get("q", "").strip()
        if self.tab == "movements":
            queryset = InventoryMovement.objects.select_related(
                "item", "intervention", "recorded_by"
            )
            movement_type = self.request.GET.get("movement_type", "").strip()
            item_id = self.request.GET.get("item", "").strip()
            date_range = parse_inclusive_date_range(self.request.GET, label="movement")
            self.filter_date_error = date_range.error
            if query:
                filters = (
                    Q(item__name__icontains=query)
                    | Q(item__item_code__icontains=query)
                    | Q(reference__icontains=query)
                    | Q(intervention__description__icontains=query)
                )
                reference_number = query.upper().removeprefix("STK-")
                if reference_number.isdigit():
                    filters |= Q(pk=int(reference_number))
                queryset = queryset.filter(filters)
            if movement_type in dict(InventoryMovement.MOVEMENT_CHOICES):
                queryset = queryset.filter(movement_type=movement_type)
            if item_id.isdigit():
                queryset = queryset.filter(item_id=int(item_id))
            if not date_range.error:
                if date_range.start:
                    queryset = queryset.filter(created_at__date__gte=date_range.start)
                if date_range.end:
                    queryset = queryset.filter(created_at__date__lte=date_range.end)
            return queryset.order_by("-created_at", "-pk")

        queryset = InventoryItem.objects.all()
        category = self.request.GET.get("category", "").strip()
        status = self.request.GET.get("status", "").strip()
        location = self.request.GET.get("location", "").strip()
        record_status = self.request.GET.get("record_status", "active")
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(item_code__icontains=query)
                | Q(storage_location__icontains=query)
            )
        if category in dict(InventoryItem.CATEGORY_CHOICES):
            queryset = queryset.filter(category=category)
        if location:
            queryset = queryset.filter(storage_location=location)
        if record_status == "archived":
            queryset = queryset.filter(is_active=False)
        elif record_status != "all":
            queryset = queryset.filter(is_active=True)
        expiring_cutoff = timezone.localdate() + timedelta(days=30)
        if status == "out":
            queryset = queryset.filter(stock_on_hand__lte=0)
        elif status == "low":
            queryset = queryset.filter(stock_on_hand__gt=0, stock_on_hand__lte=F("reorder_level")).filter(
                Q(expiration_date__isnull=True) | Q(expiration_date__gt=expiring_cutoff)
            )
        elif status == "expiring":
            queryset = queryset.filter(stock_on_hand__gt=0, expiration_date__lte=expiring_cutoff)
        elif status == "in":
            queryset = queryset.filter(stock_on_hand__gt=F("reorder_level")).filter(
                Q(expiration_date__isnull=True) | Q(expiration_date__gt=expiring_cutoff)
            )
        return queryset.order_by("name", "item_code")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_items = InventoryItem.objects.filter(is_active=True)
        expiring_cutoff = timezone.localdate() + timedelta(days=30)
        stock_summary = active_items.aggregate(
            total=Count("pk"),
            low=Count(
                "pk",
                filter=Q(stock_on_hand__gt=0, stock_on_hand__lte=F("reorder_level"))
                & (Q(expiration_date__isnull=True) | Q(expiration_date__gt=expiring_cutoff)),
            ),
            out=Count("pk", filter=Q(stock_on_hand__lte=0)),
            expiring=Count(
                "pk",
                filter=Q(stock_on_hand__gt=0, expiration_date__lte=expiring_cutoff),
            ),
        )
        context.update(
            {
                "tab": self.tab,
                "category_choices": InventoryItem.CATEGORY_CHOICES,
                "movement_choices": InventoryMovement.MOVEMENT_CHOICES,
                "total_items": stock_summary["total"],
                "low_stock_count": stock_summary["low"],
                "out_of_stock_count": stock_summary["out"],
                "expiring_count": stock_summary["expiring"],
                "movement_count": InventoryMovement.objects.count(),
                "filter_date_error": getattr(self, "filter_date_error", ""),
            }
        )
        if self.tab == "movements":
            context["inventory_items"] = active_items.only(
                "pk", "item_code", "name"
            ).order_by("name", "item_code")
        else:
            context["locations"] = (
                InventoryItem.objects.exclude(storage_location="")
                .values_list("storage_location", flat=True)
                .distinct()
                .order_by("storage_location")
            )
        return context


class InventoryItemCreateView(InventoryAccessMixin, CreateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "inventory/item_form.html"
    success_url = reverse_lazy("inventory:list")

    def form_valid(self, form):
        response = super().form_valid(form)
        record_request_event(
            self.request,
            title="Inventory Item Created",
            module="Inventory",
            description=f"{self.request.user.display_name} created an inventory item.",
            target_label=self.object.item_code,
            details=[
                {"field": "Item", "after": self.object.name},
                {"field": "Category", "after": self.object.get_category_display()},
                {"field": "Storage location", "after": self.object.storage_location},
            ],
        )
        messages.success(
            self.request,
            f"{self.object.name} was added. Record a stock receipt to enter its opening balance.",
        )
        return response


class InventoryItemUpdateView(InventoryAccessMixin, UpdateView):
    model = InventoryItem
    form_class = InventoryItemForm
    template_name = "inventory/item_form.html"

    def get_success_url(self):
        return reverse_lazy("inventory:detail", args=[self.object.pk])

    def form_valid(self, form):
        response = super().form_valid(form)
        record_request_event(
            self.request,
            title="Inventory Item Updated",
            module="Inventory",
            description=f"{self.request.user.display_name} updated an inventory item.",
            target_label=self.object.item_code,
        )
        messages.success(self.request, f"{self.object.name} was updated.")
        return response


class InventoryItemDetailView(InventoryAccessMixin, DetailView):
    model = InventoryItem
    template_name = "inventory/detail.html"

    def get_queryset(self):
        return InventoryItem.objects.prefetch_related("movements__intervention")


class InventoryMovementCreateView(InventoryAccessMixin, FormView):
    form_class = InventoryMovementForm
    template_name = "inventory/movement_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        if self.request.GET.get("item", "").isdigit():
            initial["item"] = int(self.request.GET["item"])
        if self.request.GET.get("intervention", "").isdigit():
            initial["intervention"] = int(self.request.GET["intervention"])
            initial["movement_type"] = InventoryMovement.RELEASE
        return initial

    def form_valid(self, form):
        cleaned = form.cleaned_data.copy()
        service_request = cleaned.pop("service_request", None)
        try:
            with transaction.atomic():
                if (
                    cleaned["movement_type"] == InventoryMovement.RELEASE
                    and service_request
                    and cleaned.get("intervention") is None
                ):
                    cleaned["intervention"] = ensure_inventory_release_intervention(
                        service_request,
                        actor=self.request.user,
                        description=f"Released {cleaned['item'].name} for {service_request.subject}",
                        quantity=cleaned["quantity"],
                        unit=cleaned["item"].unit,
                    )
                movement = record_inventory_movement(
                    **cleaned,
                    recorded_by=self.request.user,
                )
        except ValidationError as error:
            form.add_error("quantity", error.messages[0])
            return self.form_invalid(form)
        record_request_event(
            self.request,
            title="Inventory Movement Recorded",
            module="Inventory",
            description=f"{self.request.user.display_name} recorded a stock movement.",
            target_label=movement.movement_id,
            details=[
                {"field": "Item", "after": movement.item.name},
                {"field": "Movement", "after": movement.get_movement_type_display()},
                {"field": "Quantity", "after": f"{movement.quantity} {movement.item.unit}"},
                {"field": "Balance", "after": f"{movement.balance_after} {movement.item.unit}"},
                {
                    "field": "Intervention",
                    "after": movement.intervention.reference_id if movement.intervention_id else "Not linked",
                },
                {
                    "field": "Service request",
                    "after": (
                        movement.intervention.service_request.request_id
                        if movement.intervention_id
                        and movement.intervention.service_request_id
                        else "Not linked"
                    ),
                },
            ],
        )
        messages.success(
            self.request,
            f"{movement.movement_id} was recorded. Current balance: {movement.balance_after} {movement.item.unit}.",
        )
        return redirect("inventory:detail", pk=movement.item_id)


class InventoryItemArchiveView(InventoryAccessMixin, View):
    def post(self, request, pk):
        item = get_object_or_404(InventoryItem, pk=pk)
        restoring = request.POST.get("action") == "restore"
        if not restoring and item.stock_on_hand > 0:
            messages.error(
                request,
                "An item with remaining stock cannot be archived. Record the appropriate release or adjustment first.",
            )
            return redirect("inventory:detail", pk=item.pk)
        item.is_active = restoring
        item.save(update_fields=["is_active", "updated_at"])
        action = "restored" if restoring else "archived"
        record_request_event(
            request,
            title=f"Inventory Item {action.title()}",
            module="Inventory",
            description=f"{request.user.display_name} {action} an inventory item.",
            target_label=item.item_code,
        )
        messages.success(request, f"{item.name} was {action}.")
        return redirect("inventory:list")
