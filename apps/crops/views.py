from django.contrib import messages
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.db import transaction
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from urllib.parse import urlencode

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows, farmer_update_rows
from apps.farmers.history import farmer_snapshot, record_farmer_update
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
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
    model = Farmer
    template_name = "crops/list.html"
    paginate_by = 10

    def get_queryset(self):
        crops = CropRecord.objects.select_related("parcel", "parcel__farmer")
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
            crops = crops.filter(filters)
        if crop_type:
            crops = crops.filter(crop_type=crop_type)
        if year.isdigit():
            crops = crops.filter(planting_date__year=int(year))
        if status == "archived":
            crops = crops.filter(is_active=False)
        else:
            crops = crops.filter(is_active=True)

        parcel_queryset = FarmParcel.objects.order_by("pk").prefetch_related(
            Prefetch(
                "crops",
                queryset=crops.order_by("crop_type", "planting_date", "pk"),
                to_attr="listed_crops",
            )
        )
        return (
            Farmer.objects.filter(is_active=True, pk__in=crops.values("parcel__farmer_id"))
            .prefetch_related(
                Prefetch("parcels", queryset=parcel_queryset, to_attr="listed_parcels")
            )
            .distinct()
            .order_by("pk")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["crop_types"] = (
            CropRecord.objects.values_list("crop_type", flat=True).distinct().order_by("crop_type")
        )
        context["years"] = CropRecord.objects.dates("planting_date", "year", order="DESC")
        for farmer in context["object_list"]:
            farmer.listed_crop_records = [
                crop
                for parcel in farmer.listed_parcels
                for crop in parcel.listed_crops
            ]
            farmer.listed_crop_names = ", ".join(
                dict.fromkeys(crop.crop_type for crop in farmer.listed_crop_records)
            )
            farmer.listed_planting_dates = ", ".join(
                dict.fromkeys(
                    crop.planting_date.strftime("%b %d, %Y")
                    for crop in farmer.listed_crop_records
                    if crop.planting_date
                )
            ) or "Not set"
        return context


class CropDetailView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareCropMixin, DetailView):
    model = CropRecord
    template_name = "crops/detail.html"

    def get_queryset(self):
        return CropRecord.objects.select_related("parcel", "parcel__farmer")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class FarmerCropDetailView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareCropMixin, DetailView
):
    model = Farmer
    template_name = "crops/farmer_detail.html"

    def get_queryset(self):
        parcels = FarmParcel.objects.order_by("pk").prefetch_related(
            Prefetch(
                "crops",
                queryset=CropRecord.objects.filter(is_active=True).order_by(
                    "-planting_date", "pk"
                ),
                to_attr="current_crop_records",
            ),
            Prefetch(
                "crops",
                queryset=CropRecord.objects.filter(is_active=False).order_by(
                    "-planting_date", "pk"
                ),
                to_attr="archived_crop_records",
            ),
        )
        return Farmer.objects.filter(is_active=True).prefetch_related(
            Prefetch("parcels", queryset=parcels, to_attr="crop_record_parcels")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_crop_records"] = [
            crop
            for parcel in self.object.crop_record_parcels
            for crop in parcel.current_crop_records
        ]
        context["archived_crop_records"] = [
            crop
            for parcel in self.object.crop_record_parcels
            for crop in parcel.archived_crop_records
        ]
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

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        farmer_id = self.request.GET.get("farmer", "")
        if farmer_id.isdigit():
            form.fields["parcel"].queryset = FarmParcel.objects.select_related(
                "farmer"
            ).filter(farmer_id=farmer_id, farmer__is_active=True, is_active=True)
        return form

    def get_initial(self):
        initial = super().get_initial()
        parcel_id = self.request.GET.get("parcel", "")
        if parcel_id.isdigit():
            parcel = FarmParcel.objects.filter(pk=parcel_id, is_active=True).first()
            if parcel:
                initial["parcel"] = parcel
        farmer_id = self.request.GET.get("farmer", "")
        if not parcel_id and farmer_id.isdigit():
            farmer_parcels = list(
                FarmParcel.objects.filter(farmer_id=farmer_id, is_active=True)[:2]
            )
            if len(farmer_parcels) == 1:
                initial["parcel"] = farmer_parcels[0]
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        parcel_id = self.request.GET.get("parcel", "")
        context["source_parcel"] = (
            FarmParcel.objects.select_related("farmer")
            .filter(pk=parcel_id, is_active=True)
            .first()
            if parcel_id.isdigit()
            else None
        )
        farmer_id = self.request.GET.get("farmer", "")
        context["source_farmer"] = (
            Farmer.objects.filter(pk=farmer_id, is_active=True).first()
            if farmer_id.isdigit()
            else None
        )
        return context

    def get_success_url(self):
        if self.request.GET.get("parcel") == str(self.object.parcel_id):
            return reverse("farm_parcels:detail", args=[self.object.parcel_id])
        if self.request.GET.get("farmer") == str(self.object.parcel.farmer_id):
            return reverse("crops:farmer_detail", args=[self.object.parcel.farmer_id])
        return reverse("crops:list")


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


class FarmerCropArchiveView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Archive or restore the crop records represented by one grouped farmer row."""

    def post(self, request, pk):
        farmer = get_object_or_404(Farmer, pk=pk, is_active=True)
        restoring = request.POST.get("action") == "restore"
        records = CropRecord.objects.filter(
            parcel__farmer=farmer,
            is_active=not restoring,
        )
        crop_type = request.POST.get("crop_type", "").strip()
        year = request.POST.get("year", "").strip()
        if crop_type:
            records = records.filter(crop_type=crop_type)
        if year.isdigit():
            records = records.filter(planting_date__year=int(year))

        record_count = records.count()
        if record_count:
            with transaction.atomic():
                records.update(
                    is_active=restoring,
                    archived_at=None if restoring else timezone.now(),
                    archived_by=None if restoring else request.user,
                )
                action = "restored" if restoring else "archived"
                record_request_event(
                    request,
                    title=f"Farmer Crop Records {action.title()}",
                    module="Crops",
                    description=(
                        f"{request.user.display_name} {action} {record_count} crop "
                        f"record{'s' if record_count != 1 else ''}."
                    ),
                    target_label=f"{farmer.record_id} - {farmer.full_name}",
                )
            messages.success(
                request,
                f"{record_count} crop record{'s were' if record_count != 1 else ' was'} "
                f"{action}; no data was deleted.",
            )
        else:
            messages.info(request, "No matching crop records needed to be changed.")

        query = {
            key: request.POST.get(key)
            for key in ("q", "crop_type", "year", "status")
            if request.POST.get(key)
        }
        destination = reverse("crops:list")
        if query:
            destination = f"{destination}?{urlencode(query)}"
        return redirect(destination)
