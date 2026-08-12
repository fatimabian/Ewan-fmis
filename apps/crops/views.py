from datetime import date

from django.db.models import Q
from django.urls import reverse_lazy
from django.db import transaction
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
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


class CropDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, DeleteView):
    model = CropRecord
    success_url = reverse_lazy("crops:list")
