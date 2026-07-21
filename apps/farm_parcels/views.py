import re

from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.farmers.models import Farmer
from .forms import FarmParcelForm
from .models import FarmParcel


class RoleAwareParcelMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = "base/admin_base.html" if self.request.user.is_admin else "base/staff_base.html"
        return context


class FarmParcelListView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, ListView):
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
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["barangays"] = FarmParcel.objects.values_list("barangay", flat=True).distinct().order_by("barangay")
        context["ownership_choices"] = FarmParcel._meta.get_field("ownership_type").choices
        return context


class FarmParcelDetailView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, DetailView):
    model = FarmParcel
    template_name = "farm_parcels/detail.html"

    def get_queryset(self):
        return FarmParcel.objects.select_related("farmer").prefetch_related("crops")


class FarmParcelMapView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, TemplateView):
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
        farmers = Farmer.objects.filter(is_active=True).prefetch_related("parcels__crops").order_by("last_name", "first_name")
        markers = []
        unmapped = []
        for farmer in farmers:
            point = self.parse_coordinates(farmer.location_coordinates)
            if point is None:
                point = next(
                    (parsed for parcel in farmer.parcels.all() if (parsed := self.parse_coordinates(parcel.coordinates))),
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
                            "image": crop.image.url if crop.image else "",
                        }
                    )
            markers.append(
                {
                    "id": farmer.pk,
                    "farmer_id": farmer.record_id,
                    "farmer": farmer.full_name,
                    "address": ", ".join(part for part in (farmer.house_lot_purok, farmer.street_sitio, farmer.barangay) if part),
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
        return context


class FarmerLocationPinView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def post(self, request):
        farmer = get_object_or_404(Farmer, pk=request.POST.get("farmer_id"), is_active=True)
        try:
            latitude = float(request.POST.get("latitude", ""))
            longitude = float(request.POST.get("longitude", ""))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "message": "Choose a valid point on the map."}, status=400)
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return JsonResponse({"ok": False, "message": "The selected map coordinates are invalid."}, status=400)
        farmer.location_coordinates = f"{latitude:.7f}, {longitude:.7f}"
        farmer.save(update_fields=["location_coordinates"])
        return JsonResponse({"ok": True, "message": f"{farmer.full_name}'s map location was saved."})


class FarmParcelCreateView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, CreateView):
    form_class = FarmParcelForm
    template_name = "farm_parcels/form.html"
    success_url = reverse_lazy("farm_parcels:list")


class FarmParcelUpdateView(FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, UpdateView):
    model = FarmParcel
    form_class = FarmParcelForm
    template_name = "farm_parcels/form.html"
    success_url = reverse_lazy("farm_parcels:list")


class FarmParcelDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, DeleteView):
    model = FarmParcel
    success_url = reverse_lazy("farm_parcels:list")
