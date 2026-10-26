import re
import mimetypes

from django.contrib import messages
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.cache import patch_cache_control
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
from apps.common.constants import commodity_group
from apps.common.crop_symbols import crop_symbol
from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows, farmer_update_rows
from apps.farmers.history import farmer_snapshot, record_farmer_update
from apps.crops.models import CropRecord
from .forms import FarmParcelForm, FarmParcelPhotoUploadForm
from .models import FarmParcel, FarmParcelPhoto
from .rosario_boundary import ROSARIO_BOUNDARY


# Municipal extent and simplified administrative outline. The same polygon is
# enforced by the browser and the save endpoint so out-of-town coordinates
# cannot be stored by bypassing the map controls.
ROSARIO_MAP_BOUNDS = {
    "south": 13.6852949,
    "west": 121.1638677,
    "north": 13.8700758,
    "east": 121.3710798,
}
ROSARIO_MAP_CENTER = [13.7776854, 121.2674738]


def is_within_rosario(latitude, longitude):
    if not (
        ROSARIO_MAP_BOUNDS["south"] <= latitude <= ROSARIO_MAP_BOUNDS["north"]
        and ROSARIO_MAP_BOUNDS["west"] <= longitude <= ROSARIO_MAP_BOUNDS["east"]
    ):
        return False
    inside = False
    previous_latitude, previous_longitude = ROSARIO_BOUNDARY[-1]
    for current_latitude, current_longitude in ROSARIO_BOUNDARY:
        crosses_latitude = (current_latitude > latitude) != (previous_latitude > latitude)
        if crosses_latitude:
            boundary_longitude = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < boundary_longitude:
                inside = not inside
        previous_latitude, previous_longitude = current_latitude, current_longitude
    return inside


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
    def get_queryset(self):
        queryset = FarmParcel.objects.select_related("farmer")
        query = self.request.GET.get("q", "").strip()
        barangay = self.request.GET.get("barangay", "").strip()
        ownership = self.request.GET.get("ownership", "").strip()
        area = self.request.GET.get("area", "").strip()
        status = self.request.GET.get("status", "all").strip()
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
        if status == "inactive":
            queryset = queryset.filter(is_active=False)
        elif status != "all":
            queryset = queryset.filter(is_active=True)
        # Show every saved parcel by default, including inactive records, with
        # the most recently registered parcel first for immediate verification.
        return queryset.order_by("-created_at", "-pk")

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
        )[:1]
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
        context.update({"history_title": "Farm Parcel Update Record History", "record_label": f"{self.object.display_name} · {self.object.farmer.full_name}", "back_url": reverse("farm_parcels:detail", args=[self.object.pk]), "edit_url": reverse("farm_parcels:edit", args=[self.object.pk]) if self.object.is_active else "", "edit_label": "Update Record", "history_entries": rows})
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
        # Keep the initial HTML response small. Marker details and parcel-search
        # choices are fetched after the map shell is visible instead of rendering
        # thousands of records, photos, and <option> elements into this page.
        parcels = FarmParcel.objects.filter(is_active=True, farmer__is_active=True)
        parcel_totals = parcels.aggregate(
            total=Count("pk"),
            mapped=Count(
                "pk",
                filter=~Q(coordinates="") & Q(coordinates__isnull=False),
            ),
        )
        context["mapped_count"] = parcel_totals["mapped"]
        context["unmapped_count"] = max(
            0, parcel_totals["total"] - parcel_totals["mapped"]
        )
        context["rosario_map_bounds"] = ROSARIO_MAP_BOUNDS
        context["rosario_map_center"] = ROSARIO_MAP_CENTER
        context["rosario_boundary"] = ROSARIO_BOUNDARY
        return context


class FarmParcelMapDataView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Return compact map data after the page shell has rendered."""

    def get(self, request):
        active_parcels = FarmParcel.objects.filter(
            is_active=True,
            farmer__is_active=True,
        )
        totals_by_barangay = dict(
            active_parcels.values("barangay")
            .annotate(total=Count("pk"))
            .values_list("barangay", "total")
        )
        parcels = (
            active_parcels
            .exclude(coordinates="")
            .only(
                "pk",
                "coordinates",
                "barangay",
            )
            .prefetch_related(
                Prefetch(
                    "crops",
                    queryset=CropRecord.objects.filter(is_active=True)
                    .only("parcel_id", "crop_type")
                    .order_by("crop_type", "pk"),
                    to_attr="map_crops",
                )
            )
            .order_by("pk")
        )
        markers = []
        mapped_by_barangay = {}
        for parcel in parcels.iterator(chunk_size=500):
            point = FarmParcelMapView.parse_coordinates(parcel.coordinates)
            if not point or not is_within_rosario(*point):
                continue
            commodity_groups = sorted(
                {commodity_group(crop.crop_type) for crop in parcel.map_crops}
            )
            markers.append(
                {
                    "id": parcel.pk,
                    "parcel": parcel.display_name,
                    "barangay": parcel.barangay,
                    "crops": [
                        {"name": name, "symbol": crop_symbol(name)}
                        for name in commodity_groups
                    ],
                    "lat": point[0],
                    "lng": point[1],
                }
            )
            mapped_by_barangay[parcel.barangay] = (
                mapped_by_barangay.get(parcel.barangay, 0) + 1
            )
        total_count = sum(totals_by_barangay.values())
        response = JsonResponse(
            {
                "markers": markers,
                "count": len(markers),
                "unmapped_count": max(0, total_count - len(markers)),
                "barangay_counts": {
                    barangay: {
                        "total": total,
                        "mapped": mapped_by_barangay.get(barangay, 0),
                        "unmapped": max(
                            0, total - mapped_by_barangay.get(barangay, 0)
                        ),
                    }
                    for barangay, total in totals_by_barangay.items()
                },
            }
        )
        patch_cache_control(response, no_store=True, private=True)
        return response


class FarmParcelMapDetailView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Fetch private popup fields only after an authorized user selects a pin."""

    def get(self, request, pk):
        parcel = get_object_or_404(
            FarmParcel.objects.filter(is_active=True, farmer__is_active=True)
            .select_related("farmer")
            .only(
                "pk", "area_hectares", "barangay", "farmer__id",
                "farmer__first_name", "farmer__middle_name",
                "farmer__last_name", "farmer__extension_name",
            ),
            pk=pk,
        )
        return JsonResponse(
            {
                "id": parcel.pk,
                "farmer_id": parcel.farmer.record_id,
                "farmer": parcel.farmer.full_name,
                "parcel": parcel.display_name,
                "area": f"{parcel.area_hectares} ha",
                "address": f"{parcel.barangay}, Rosario, Batangas",
                "edit_url": reverse("farm_parcels:detail", args=[parcel.pk]),
            }
        )


class FarmParcelMapSearchView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Search parcels without placing every record in a large HTML select."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        parcels = FarmParcel.objects.filter(
            is_active=True,
            farmer__is_active=True,
        ).select_related("farmer")
        if query:
            farmer_id = query.upper().removeprefix("F-")
            filters = (
                Q(parcel_name__icontains=query)
                | Q(barangay__icontains=query)
                | Q(farmer__first_name__icontains=query)
                | Q(farmer__middle_name__icontains=query)
                | Q(farmer__last_name__icontains=query)
                | Q(farmer__rsbsa_number__icontains=query)
            )
            if farmer_id.isdigit():
                filters |= Q(farmer_id=int(farmer_id))
            parcels = parcels.filter(filters)
        results = [
            {
                "id": parcel.pk,
                "label": (
                    f"{parcel.farmer.record_id} — {parcel.farmer.full_name} / "
                    f"{parcel.display_name} ({parcel.barangay})"
                ),
                "livelihood": parcel.farmer.get_livelihood_display(),
                "livelihood_code": parcel.farmer.livelihood,
                "activities": parcel.farmer.activities,
                "activities_display": parcel.farmer.activities_display,
            }
            for parcel in parcels.order_by("-created_at", "-pk")[:40]
        ]
        return JsonResponse({"results": results})


class FarmerLocationPinView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def post(self, request):
        parcel = get_object_or_404(
            FarmParcel,
            pk=request.POST.get("parcel_id"),
            is_active=True,
            farmer__is_active=True,
        )
        operation = request.POST.get("operation", "create")
        if operation == "remove":
            previous_coordinates = parcel.coordinates.strip()
            parcel.coordinates = ""
            parcel.save(update_fields=["coordinates"])
            record_request_event(
                request,
                title="Farm Parcel Map Pin Removed",
                module="Farm Parcels",
                description=f"{request.user.display_name} removed an incorrect farm parcel map pin.",
                target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
                reason="Cleared an incorrect or no longer applicable parcel location.",
                details=[{
                    "field": "Farm parcel coordinates",
                    "before": previous_coordinates or "Not previously pinned",
                    "after": "Not pinned",
                }],
            )
            return JsonResponse(
                {
                    "ok": True,
                    "message": f"{parcel.display_name}'s map pin was removed.",
                }
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
        is_update = bool(getattr(self, "object", None) and self.object.pk)
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
        if not is_update:
            messages.success(self.request, "The farm parcel was saved.")
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
        return f'{reverse("farm_parcels:detail", args=[self.object.pk])}?saved=slip-b'


class FarmParcelDeleteView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Archive or restore a parcel while retaining its crops and history."""

    def post(self, request, pk):
        parcel = get_object_or_404(FarmParcel, pk=pk)
        restoring = request.POST.get("action") == "restore"
        parcel.is_active = restoring
        parcel.save(update_fields=["is_active"])
        action = "restored" if restoring else "set to inactive"
        record_request_event(
            request,
            title="Farm Parcel Restored" if restoring else "Farm Parcel Set Inactive",
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
                "Choose one valid field photo.",
            )
            messages.error(request, error)
            return redirect("farm_parcels:detail", pk=parcel.pk)

        upload = form.cleaned_data["field_photo"][0]
        with transaction.atomic():
            locked_parcel = FarmParcel.objects.select_for_update().get(pk=parcel.pk)
            current_photos = FarmParcelPhoto.objects.filter(
                parcel=locked_parcel,
                is_active=True,
            )
            replaced_photo = current_photos.exists()
            current_photos.update(
                is_active=False,
                archived_at=timezone.now(),
                archived_by=request.user,
            )
            FarmParcelPhoto.objects.create(
                parcel=locked_parcel,
                image=upload,
                uploaded_by=request.user,
            )
            record_request_event(
                request,
                title="Farm Parcel Photo Replaced" if replaced_photo else "Farm Parcel Photo Added",
                module="Farm Parcels",
                description=(
                    f"{request.user.display_name} "
                    f"{'replaced the' if replaced_photo else 'added an'} office field photo."
                ),
                target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
                reason="Office field documentation for parcel review and decision-making.",
                details=[
                    {
                        "field": "Field photo gallery",
                        "before": "Previous photo archived" if replaced_photo else "No current photo",
                        "after": "One current photo",
                    }
                ],
            )
        messages.success(request, "The field photo was replaced." if replaced_photo else "The field photo was uploaded.")
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
