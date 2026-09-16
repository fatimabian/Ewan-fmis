from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.db import transaction
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows, farmer_update_rows
from apps.farmers.history import farmer_snapshot, record_farmer_update
from .forms import CropRecordForm
from .models import CropRecord


class RoleAwareCropMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        )
        return context


class CropListView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareCropMixin, ListView):
    model = CropRecord
    template_name = "crops/list.html"
    paginate_by = 10

    def get_queryset(self):
        queryset = CropRecord.objects.select_related("parcel", "parcel__farmer").order_by(
            "-planting_date", "crop_type"
        )
        query = self.request.GET.get("q", "").strip()
        crop_type = self.request.GET.get("crop_type", "").strip()
        year = self.request.GET.get("year", "").strip()
        status = self.request.GET.get("status", "").strip()

        if query:
            farmer_id = query.upper().removeprefix("F-")
            filters = (
                Q(crop_type__icontains=query)
                | Q(parcel__parcel_name__icontains=query)
                | Q(parcel__farmer__first_name__icontains=query)
                | Q(parcel__farmer__last_name__icontains=query)
                | Q(parcel__farmer__rsbsa_number__icontains=query)
                | Q(parcel__farmer__barangay__icontains=query)
            )
            if farmer_id.isdigit():
                filters |= Q(parcel__farmer_id=int(farmer_id))
            queryset = queryset.filter(filters)
        if crop_type:
            queryset = queryset.filter(crop_type=crop_type)
        if year.isdigit():
            queryset = queryset.filter(planting_date__year=int(year))
        if status == "archived":
            queryset = queryset.filter(is_active=False)
        else:
            queryset = queryset.filter(is_active=True)
        if status == "growing":
            queryset = queryset.filter(
                Q(harvest_date__isnull=True) | Q(harvest_date__gt=date.today())
            )
        elif status == "harvested":
            queryset = queryset.filter(harvest_date__lte=date.today())
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["crop_types"] = (
            CropRecord.objects.values_list("crop_type", flat=True).distinct().order_by("crop_type")
        )
        context["years"] = CropRecord.objects.dates("planting_date", "year", order="DESC")
        context["today"] = date.today()
        return context


class CropDetailView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareCropMixin, DetailView):
    model = CropRecord
    template_name = "crops/detail.html"

    def get_queryset(self):
        return CropRecord.objects.select_related("parcel", "parcel__farmer")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["today"] = date.today()
        return context


class CropHistoryView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareCropMixin, DetailView):
    model = CropRecord
    template_name = "shared/record_history.html"

    def get_queryset(self):
        return CropRecord.objects.select_related("parcel", "parcel__farmer")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        farmer = self.object.parcel.farmer
        parcels = list(farmer.parcels.order_by("pk"))
        parcel_number = next((index for index, parcel in enumerate(parcels, 1) if parcel.pk == self.object.parcel_id), 0)
        crops = list(self.object.parcel.crops.order_by("pk"))
        crop_number = next((index for index, crop in enumerate(crops, 1) if crop.pk == self.object.pk), 0)
        prefix = f"Parcel {parcel_number} / Commodity {crop_number} /"
        updates = []
        for entry in farmer.update_history.filter(update_type="SLIP_B").select_related("actor"):
            if any(change.get("field", "").startswith(prefix) for change in entry.changes):
                updates.append(entry)
        events = ActivityLog.objects.filter(module="Crops", target_label=f"{farmer.record_id} - {self.object.crop_type}").select_related("actor")
        rows = farmer_update_rows(updates) + activity_rows(events)
        rows.sort(key=lambda row: row["date"], reverse=True)
        context.update({"history_title": "Crop Record Update History", "record_label": f"{self.object.crop_type} · {farmer.full_name}", "back_url": reverse("crops:detail", args=[self.object.pk]), "edit_url": reverse("crops:edit", args=[self.object.pk]) if self.object.is_active else "", "edit_label": "Edit Crop", "history_entries": rows})
        return context


class CropHistoryMixin:
    def post(self, request, *args, **kwargs):
        if kwargs.get("pk"):
            current = self.get_object()
            self.snapshot_before_update = farmer_snapshot(current.parcel.farmer)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        farmer = form.cleaned_data["parcel"].farmer
        before = getattr(self, "snapshot_before_update", None) or farmer_snapshot(farmer)
        with transaction.atomic():
            response = super().form_valid(form)
            record_farmer_update(
                farmer=farmer,
                actor=self.request.user,
                update_type="SLIP_B",
                before=before,
                remarks=f"Commodity record updated: {self.object.crop_type}",
            )
        return response


class CropCreateView(
    FMISLoginRequiredMixin,
    StaffRequiredMixin,
    RoleAwareCropMixin,
    CropHistoryMixin,
    CreateView,
):
    form_class = CropRecordForm
    template_name = "crops/form.html"
    success_url = reverse_lazy("crops:list")


class CropUpdateView(
    FMISLoginRequiredMixin,
    StaffRequiredMixin,
    RoleAwareCropMixin,
    CropHistoryMixin,
    UpdateView,
):
    model = CropRecord
    form_class = CropRecordForm
    template_name = "crops/form.html"
    success_url = reverse_lazy("crops:list")


class CropDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Archive or restore a crop record without destroying its audit history."""

    def post(self, request, pk):
        crop = get_object_or_404(CropRecord, pk=pk)
        restoring = request.POST.get("action") == "restore"
        crop.is_active = restoring
        crop.archived_at = None if restoring else timezone.now()
        crop.archived_by = None if restoring else request.user
        crop.save(update_fields=["is_active", "archived_at", "archived_by"])
        action = "restored" if restoring else "archived"
        record_request_event(
            request,
            title=f"Crop Record {action.title()}",
            module="Crops",
            description=f"{request.user.display_name} {action} a crop record without deleting it.",
            target_label=f"{crop.parcel.farmer.record_id} - {crop.crop_type}",
        )
        messages.success(request, f"{crop.crop_type} crop record was {action}; no data was deleted.")
        return redirect("crops:list")
