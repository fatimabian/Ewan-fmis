import re

from django.db.models import Q
from django.http import JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.common.crop_symbols import crop_symbol
from apps.activity_logs.models import ActivityLog
from apps.farmers.models import Farmer
from apps.farmers.history import farmer_snapshot, record_farmer_update
from .forms import FarmParcelForm, ParcelCropFormSet
from .models import FarmParcel


# Municipal extent published in Rosario's planning references. The same extent
# is enforced by the browser and the save endpoint so out-of-town coordinates
# cannot be stored by bypassing the map controls.
ROSARIO_MAP_BOUNDS = {
    "south": 13.685278,
    "west": 121.166667,
    "north": 13.875278,
    "east": 121.333333,
}
ROSARIO_MAP_CENTER = [13.8467, 121.2060]


def is_within_rosario(latitude, longitude):
    return (
        ROSARIO_MAP_BOUNDS["south"] <= latitude <= ROSARIO_MAP_BOUNDS["north"]
        and ROSARIO_MAP_BOUNDS["west"] <= longitude <= ROSARIO_MAP_BOUNDS["east"]
    )


class RoleAwareParcelMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        )
        return context


class FarmParcelListView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, ListView
):
    model = FarmParcel
    template_name = "farm_parcels/list.html"
    paginate_by = 10

    def get_queryset(self):
        queryset = FarmParcel.objects.select_related("farmer")
        query = self.request.GET.get("q", "").strip()
        barangay = self.request.GET.get("barangay", "").strip()
        ownership = self.request.GET.get("ownership", "").strip()
        status = self.request.GET.get("status", "").strip()
        area = self.request.GET.get("area", "").strip()
        if query:
            farmer_id = query.upper().removeprefix("F-")
            filters = (
                Q(parcel_name__icontains=query)
                | Q(farmer__first_name__icontains=query)
                | Q(farmer__last_name__icontains=query)
                | Q(farmer__rsbsa_number__icontains=query)
                | Q(farmer__barangay__icontains=query)
            )
            if farmer_id.isdigit():
                filters |= Q(farmer_id=int(farmer_id))
            queryset = queryset.filter(filters)
        if barangay:
            queryset = queryset.filter(barangay=barangay)
        if ownership:
            queryset = queryset.filter(ownership_type=ownership)
        if status in {"active", "inactive"}:
            queryset = queryset.filter(is_active=status == "active")
        if area == "under1":
            queryset = queryset.filter(area_hectares__lt=1)
        elif area == "1to2":
            queryset = queryset.filter(area_hectares__gte=1, area_hectares__lte=2)
        elif area == "over2":
            queryset = queryset.filter(area_hectares__gt=2)
        return queryset.order_by("farmer__last_name", "farmer__first_name", "id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["barangays"] = (
            FarmParcel.objects.values_list("barangay", flat=True).distinct().order_by("barangay")
        )
        context["ownership_choices"] = FarmParcel._meta.get_field("ownership_type").choices
        return context


class FarmParcelDetailView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, DetailView
):
    model = FarmParcel
    template_name = "farm_parcels/detail.html"

    def get_queryset(self):
        return FarmParcel.objects.select_related("farmer").prefetch_related("crops")


class FarmParcelMapView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, TemplateView
):
    template_name = "farm_parcels/map.html"

    @staticmethod
    def parse_coordinates(value):
        numbers = re.findall(r"-?\d+(?:\.\d+)?", value or "")
        if len(numbers) < 2:
            return None
        latitude, longitude = float(numbers[0]), float(numbers[1])
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        farmers = (
            Farmer.objects.filter(is_active=True)
            .prefetch_related("parcels__crops")
            .order_by("last_name", "first_name")
        )
        markers = []
        unmapped = []
        for farmer in farmers:
            point = self.parse_coordinates(farmer.location_coordinates)
            if point and not is_within_rosario(*point):
                point = None
            if point is None:
                point = next(
                    (
                        parsed
                        for parcel in farmer.parcels.all()
                        if (parsed := self.parse_coordinates(parcel.coordinates))
                        and is_within_rosario(*parsed)
                    ),
                    None,
                )
            if point is None:
                unmapped.append(farmer)
                continue
            crops = []
            for parcel in farmer.parcels.all():
                for crop in parcel.crops.all():
                    crops.append(
                        {
                            "name": crop.crop_type,
                            "symbol": crop_symbol(crop.crop_type),
                            "image": crop.image.url if crop.image else "",
                        }
                    )
            markers.append(
                {
                    "id": farmer.pk,
                    "farmer_id": farmer.record_id,
                    "farmer": farmer.full_name,
                    "address": ", ".join(
                        part
                        for part in (farmer.house_lot_purok, farmer.street_sitio, farmer.barangay)
                        if part
                    ),
                    "crops": crops,
                    "lat": point[0],
                    "lng": point[1],
                    "edit_url": reverse("farmers:edit", args=[farmer.pk]),
                }
            )
        context["map_markers"] = markers
        context["farmers"] = farmers
        context["unmapped_farmers"] = unmapped
        context["mapped_count"] = len(markers)
        context["unmapped_count"] = len(unmapped)
        context["rosario_map_bounds"] = ROSARIO_MAP_BOUNDS
        context["rosario_map_center"] = ROSARIO_MAP_CENTER
        return context


class FarmerLocationPinView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def post(self, request):
        farmer = get_object_or_404(Farmer, pk=request.POST.get("farmer_id"), is_active=True)
        try:
            latitude = float(request.POST.get("latitude", ""))
            longitude = float(request.POST.get("longitude", ""))
        except (TypeError, ValueError):
            return JsonResponse(
                {"ok": False, "message": "Choose a valid point on the map."}, status=400
            )
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return JsonResponse(
                {"ok": False, "message": "The selected map coordinates are invalid."}, status=400
            )
        if not is_within_rosario(latitude, longitude):
            return JsonResponse(
                {
                    "ok": False,
                    "message": (
                        "That location is outside Rosario, Batangas. "
                        "Choose a point inside the Rosario map boundary."
                    ),
                },
                status=400,
            )
        previous_coordinates = farmer.location_coordinates.strip()
        new_coordinates = f"{latitude:.7f}, {longitude:.7f}"
        farmer.location_coordinates = new_coordinates
        farmer.save(update_fields=["location_coordinates"])
        operation = request.POST.get("operation", "create")
        if operation == "move" and previous_coordinates != new_coordinates:
            activity = ActivityLog.objects.create(
                actor=request.user,
                action=f"POST {request.path}",
                path=request.path,
                title="Farmer Map Pin Moved",
                description=f"{request.user.display_name} moved a farmer's saved map pin.",
                module="Farmers",
                target_label=farmer.full_name,
                reason="Corrected the farmer residence location on the Rosario map.",
                details=[
                    {
                        "field": "Map / Location Coordinates",
                        "before": previous_coordinates or "Not previously pinned",
                        "after": new_coordinates,
                    }
                ],
            )
            try:
                from apps.notifications.services import create_activity_notifications

                create_activity_notifications(activity)
            except Exception:
                pass
            request._fmis_activity_recorded = True
        return JsonResponse(
            {
                "ok": True,
                "message": (
                    f"{farmer.full_name}'s map pin was moved and recorded in activity history."
                    if operation == "move"
                    else f"{farmer.full_name}'s map location was saved."
                ),
            }
        )


class ParcelCropFormSetMixin:
    crop_prefix = "parcel_crops"

    def get_crop_formset(self, instance, data=None, files=None):
        return ParcelCropFormSet(
            data=data,
            files=files,
            instance=instance,
            prefix=self.crop_prefix,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "crop_formset" not in context:
            context["crop_formset"] = self.get_crop_formset(self.object)
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object() if getattr(self, "model", None) else None
        before = farmer_snapshot(self.object.farmer) if self.object else None
        form = self.get_form()
        if not form.is_valid():
            return self.form_invalid(form)

        parcel = form.save(commit=False)
        farmer = parcel.farmer
        if before is None:
            before = farmer_snapshot(farmer)
        crop_formset = self.get_crop_formset(parcel, request.POST, request.FILES)
        if not crop_formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, crop_formset=crop_formset)
            )

        with transaction.atomic():
            self.object = parcel
            self.object.save()
            form.save_m2m()
            crop_formset.instance = self.object
            crop_formset.save()
            record_farmer_update(
                farmer=farmer,
                actor=request.user,
                update_type="SLIP_B",
                before=before,
                transaction_code=form.cleaned_data["transaction_code"],
                change_reason=form.cleaned_data["change_reason"],
                remarks=form.cleaned_data.get("update_remarks", ""),
                date_signed=form.cleaned_data.get("date_signed"),
                date_received=form.cleaned_data.get("date_received"),
                agriculturist_name=form.cleaned_data.get("agriculturist_name", ""),
            )
        return redirect(self.get_success_url())


class FarmParcelCreateView(
    FMISLoginRequiredMixin,
    StaffRequiredMixin,
    RoleAwareParcelMixin,
    ParcelCropFormSetMixin,
    CreateView,
):
    form_class = FarmParcelForm
    template_name = "farm_parcels/form.html"
    success_url = reverse_lazy("farm_parcels:list")

    def get_initial(self):
        initial = super().get_initial()
        farmer_id = self.request.GET.get("farmer", "")
        if farmer_id.isdigit():
            initial["farmer"] = farmer_id
        return initial


class FarmParcelUpdateView(
    FMISLoginRequiredMixin,
    StaffRequiredMixin,
    RoleAwareParcelMixin,
    ParcelCropFormSetMixin,
    UpdateView,
):
    model = FarmParcel
    form_class = FarmParcelForm
    template_name = "farm_parcels/form.html"
    success_url = reverse_lazy("farm_parcels:list")


class FarmParcelDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, DeleteView):
    model = FarmParcel
    success_url = reverse_lazy("farm_parcels:list")
