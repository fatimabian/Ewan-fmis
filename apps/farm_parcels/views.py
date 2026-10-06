import re
import mimetypes

from django.contrib import messages
from django.db.models import Prefetch, Q
from django.http import FileResponse, JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.common.crop_symbols import crop_symbol
from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows, farmer_update_rows
from apps.farmers.history import farmer_snapshot, record_farmer_update
from apps.crops.models import CropRecord
from .forms import FarmParcelForm, FarmParcelPhotoUploadForm
from .models import FarmParcel, FarmParcelPhoto


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
        if area == "under1":
            queryset = queryset.filter(area_hectares__lt=1)
        elif area == "1to2":
            queryset = queryset.filter(area_hectares__gte=1, area_hectares__lte=2)
        elif area == "over2":
            queryset = queryset.filter(area_hectares__gt=2)
        return queryset.order_by("pk")

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
        return FarmParcel.objects.select_related("farmer")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["parcel_photos"] = self.object.photos.filter(is_active=True).select_related(
            "uploaded_by"
        )
        context["photo_upload_form"] = FarmParcelPhotoUploadForm()
        return context


class FarmParcelHistoryView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, DetailView
):
    model = FarmParcel
    template_name = "shared/record_history.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        parcels = list(self.object.farmer.parcels.order_by("pk"))
        parcel_number = next((index for index, parcel in enumerate(parcels, 1) if parcel.pk == self.object.pk), 0)
        prefix = f"Parcel {parcel_number} /"
        updates = []
        for entry in self.object.farmer.update_history.filter(update_type="SLIP_B").select_related("actor"):
            if any(change.get("field", "").startswith(prefix) for change in entry.changes):
                updates.append(entry)
        events = ActivityLog.objects.filter(module="Farm Parcels", target_label=f"{self.object.farmer.record_id} - {self.object.display_name}").select_related("actor")
        rows = farmer_update_rows(updates) + activity_rows(events)
        rows.sort(key=lambda row: row["date"], reverse=True)
        context.update({"history_title": "Farm Parcel Update History", "record_label": f"{self.object.display_name} · {self.object.farmer.full_name}", "back_url": reverse("farm_parcels:detail", args=[self.object.pk]), "edit_url": reverse("farm_parcels:edit", args=[self.object.pk]) if self.object.is_active else "", "edit_label": "Update Slip B", "history_entries": rows})
        return context


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
        parcels = (
            FarmParcel.objects.filter(is_active=True, farmer__is_active=True)
            .select_related("farmer")
            .prefetch_related(
                Prefetch(
                    "crops",
                    queryset=CropRecord.objects.filter(is_active=True).order_by(
                        "crop_type", "pk"
                    ),
                    to_attr="map_crops",
                ),
                Prefetch(
                    "photos",
                    queryset=FarmParcelPhoto.objects.filter(is_active=True).order_by(
                        "-created_at", "-pk"
                    ),
                    to_attr="active_field_photos",
                ),
            )
            .order_by("farmer__last_name", "farmer__first_name", "pk")
        )
        markers = []
        unmapped = []
        for parcel in parcels:
            farmer = parcel.farmer
            point = self.parse_coordinates(parcel.coordinates)
            if point and not is_within_rosario(*point):
                point = None
            if point is None:
                unmapped.append(parcel)
                continue
            crops = [
                {
                    "name": crop.crop_type,
                    "symbol": crop_symbol(crop.crop_type),
                }
                for crop in parcel.map_crops
            ]
            field_photo = (
                parcel.active_field_photos[0] if parcel.active_field_photos else None
            )
            markers.append(
                {
                    "id": parcel.pk,
                    "farmer_id": farmer.record_id,
                    "farmer": farmer.full_name,
                    "parcel": parcel.display_name,
                    "area": f"{parcel.area_hectares} ha",
                    "address": f"{parcel.barangay}, Rosario, Batangas",
                    "crops": crops,
                    "field_image_url": (
                        reverse(
                            "farm_parcels:photo_view",
                            args=[parcel.pk, field_photo.pk],
                        )
                        if field_photo
                        else ""
                    ),
                    "lat": point[0],
                    "lng": point[1],
                    "edit_url": reverse("farm_parcels:detail", args=[parcel.pk]),
                }
            )
        context["map_markers"] = markers
        context["parcels"] = parcels
        context["unmapped_parcels"] = unmapped
        context["mapped_count"] = len(markers)
        context["unmapped_count"] = len(unmapped)
        context["rosario_map_bounds"] = ROSARIO_MAP_BOUNDS
        context["rosario_map_center"] = ROSARIO_MAP_CENTER
        return context


class FarmerLocationPinView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def post(self, request):
        parcel = get_object_or_404(
            FarmParcel,
            pk=request.POST.get("parcel_id"),
            is_active=True,
            farmer__is_active=True,
        )
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
        previous_coordinates = parcel.coordinates.strip()
        new_coordinates = f"{latitude:.7f}, {longitude:.7f}"
        parcel.coordinates = new_coordinates
        parcel.save(update_fields=["coordinates"])
        operation = request.POST.get("operation", "create")
        record_request_event(
            request,
            title="Farm Parcel Map Pin Moved" if operation == "move" else "Farm Parcel Map Pin Saved",
            module="Farm Parcels",
            description=f"{request.user.display_name} recorded a farm parcel location within Rosario.",
            target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
            reason="Recorded or corrected the agricultural parcel location.",
            details=[{
                "field": "Farm parcel coordinates",
                "before": previous_coordinates or "Not previously pinned",
                "after": new_coordinates,
            }],
        )
        return JsonResponse(
            {
                "ok": True,
                "message": (
                    f"{parcel.display_name}'s map pin was moved and recorded in activity history."
                    if operation == "move"
                    else f"{parcel.display_name}'s farm location was saved."
                ),
            }
        )


class ParcelSlipBAuditMixin:
    """Save land-only changes as an official Slip B update."""

    def form_valid(self, form):
        farmer = form.cleaned_data["farmer"]
        before = farmer_snapshot(farmer)
        with transaction.atomic():
            response = super().form_valid(form)
            record_farmer_update(
                farmer=farmer,
                actor=self.request.user,
                update_type="SLIP_B",
                before=before,
                transaction_code=form.cleaned_data["transaction_code"],
                change_reason=form.cleaned_data["change_reason"],
                remarks=form.cleaned_data.get("update_remarks", ""),
                date_signed=form.cleaned_data.get("date_signed"),
                date_received=form.cleaned_data.get("date_received"),
                agriculturist_name=form.cleaned_data.get("agriculturist_name", ""),
            )
        messages.success(self.request, "The farm parcel Slip B information was saved.")
        return response


class FarmParcelCreateView(
    FMISLoginRequiredMixin,
    StaffRequiredMixin,
    RoleAwareParcelMixin,
    ParcelSlipBAuditMixin,
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
    ParcelSlipBAuditMixin,
    UpdateView,
):
    model = FarmParcel
    form_class = FarmParcelForm
    template_name = "farm_parcels/form.html"

    def get_success_url(self):
        return reverse("farm_parcels:detail", args=[self.object.pk])


class FarmParcelDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Archive or restore a parcel while retaining its crops and history."""

    def post(self, request, pk):
        parcel = get_object_or_404(FarmParcel, pk=pk)
        restoring = request.POST.get("action") == "restore"
        parcel.is_active = restoring
        parcel.save(update_fields=["is_active"])
        action = "restored" if restoring else "archived"
        record_request_event(
            request,
            title=f"Farm Parcel {action.title()}",
            module="Farm Parcels",
            description=f"{request.user.display_name} {action} a farm parcel without deleting related records.",
            target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
        )
        messages.success(request, f"{parcel.display_name} was {action}; related records were preserved.")
        return redirect("farm_parcels:list")


class FarmParcelPhotoUploadView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Add office field evidence without creating a farmer-requested Slip B update."""

    def post(self, request, pk):
        parcel = get_object_or_404(FarmParcel, pk=pk, is_active=True)
        form = FarmParcelPhotoUploadForm(request.POST, request.FILES)
        if not form.is_valid():
            error = next(
                (message for messages_list in form.errors.values() for message in messages_list),
                "Choose at least one valid field photo.",
            )
            messages.error(request, error)
            return redirect("farm_parcels:detail", pk=parcel.pk)

        uploads = form.cleaned_data["field_photos"]
        with transaction.atomic():
            for upload in uploads:
                FarmParcelPhoto.objects.create(
                    parcel=parcel,
                    image=upload,
                    uploaded_by=request.user,
                )
            record_request_event(
                request,
                title="Farm Parcel Photos Added",
                module="Farm Parcels",
                description=(
                    f"{request.user.display_name} added {len(uploads)} office field "
                    f"photo{'s' if len(uploads) != 1 else ''}."
                ),
                target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
                reason="Office field documentation for parcel review and decision-making.",
                details=[
                    {
                        "field": "Field photo gallery",
                        "before": "Existing gallery retained",
                        "after": f"{len(uploads)} new photo(s) added",
                    }
                ],
            )
        messages.success(
            request,
            f"{len(uploads)} field photo{'s were' if len(uploads) != 1 else ' was'} uploaded.",
        )
        return redirect("farm_parcels:detail", pk=parcel.pk)


class FarmParcelPhotoView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Serve field evidence only to authenticated FMIS staff."""

    def get(self, request, pk, photo_pk):
        photo = get_object_or_404(
            FarmParcelPhoto,
            pk=photo_pk,
            parcel_id=pk,
            is_active=True,
        )
        content_type = mimetypes.guess_type(photo.image.name)[0] or "application/octet-stream"
        return FileResponse(photo.image.open("rb"), content_type=content_type)


class FarmParcelPhotoArchiveView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Remove a field photo from the gallery without deleting audit evidence."""

    def post(self, request, pk, photo_pk):
        parcel = get_object_or_404(FarmParcel, pk=pk)
        photo = get_object_or_404(
            FarmParcelPhoto,
            pk=photo_pk,
            parcel=parcel,
            is_active=True,
        )
        photo.is_active = False
        photo.archived_at = timezone.now()
        photo.archived_by = request.user
        photo.save(update_fields=["is_active", "archived_at", "archived_by"])
        record_request_event(
            request,
            title="Farm Parcel Photo Removed",
            module="Farm Parcels",
            description=f"{request.user.display_name} removed a field photo from the visible gallery.",
            target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
        )
        messages.success(request, "The field photo was removed from the parcel gallery.")
        return redirect("farm_parcels:detail", pk=parcel.pk)
