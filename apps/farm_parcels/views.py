import re
import mimetypes
from collections import Counter
from math import floor

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import DatabaseError
from django.db.models import Case, Count, IntegerField, Q, Value, When
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
from apps.common.filters import parse_inclusive_date_range
from apps.common.permissions import StaffRequiredMixin
from apps.common.constants import ROSARIO_BARANGAYS, commodity_group
from apps.farm_parcels.demo_locations import ROSARIO_BARANGAY_CENTERS
from apps.common.crop_symbols import crop_symbol
from apps.activity_logs.services import record_request_event
from apps.activity_logs.models import ActivityLog
from apps.common.record_history import activity_rows, farmer_update_rows
from apps.farmers.history import farmer_snapshot, record_farmer_update
from apps.crops.models import CropRecord
from .forms import FarmParcelForm, FarmParcelPhotoUploadForm
from .coordinate_services import (
    apply_coordinate_change_immediately,
    approve_coordinate_review,
    format_coordinates,
    propose_coordinate_change,
    reject_coordinate_review,
    reverse_coordinate_history,
)
from .models import (
    FarmParcel,
    FarmParcelPhoto,
    ParcelCoordinateHistory,
    ParcelCoordinateReview,
)
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
FARM_PARCEL_CLUSTER_SIZE = 0.006
FARM_PARCEL_MAP_PAGE_SIZE = 25


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


def parcel_pin_status(coordinates, remarks=""):
    """Classify a pin without changing or estimating its stored coordinates."""
    if not (coordinates or "").strip():
        return "UNPINNED"
    point = FarmParcelMapView.parse_coordinates(coordinates)
    if (
        not point
        or not is_within_rosario(*point)
        or (remarks or "").startswith("FMIS-DEMO-DATA:")
    ):
        return "NEEDS_VERIFICATION"
    return "PINNED"


def parcel_cluster_key(latitude, longitude):
    """Return a stable display cell without altering the stored coordinates."""
    row = floor((latitude - ROSARIO_MAP_BOUNDS["south"]) / FARM_PARCEL_CLUSTER_SIZE)
    column = floor((longitude - ROSARIO_MAP_BOUNDS["west"]) / FARM_PARCEL_CLUSTER_SIZE)
    return f"{row}:{column}"


def parcel_search_filter(query):
    """Match names and identifiers, including bare, P-, and F- numbers."""
    query = (query or "").strip()
    filters = (
        Q(parcel_name__icontains=query)
        | Q(barangay__icontains=query)
        | Q(farmer__first_name__icontains=query)
        | Q(farmer__middle_name__icontains=query)
        | Q(farmer__last_name__icontains=query)
        | Q(farmer__rsbsa_number__icontains=query)
    )
    identifier = re.fullmatch(r"\s*([PF])?\s*[-#]?\s*(\d+)\s*", query, re.IGNORECASE)
    if not identifier:
        return filters
    prefix, digits = identifier.groups()
    number = int(digits)
    if not prefix or prefix.upper() == "P":
        filters |= Q(pk=number)
        # Preserve the useful type-ahead behaviour for input such as P-28.
        filters |= Q(pk__startswith=digits)
    if not prefix or prefix.upper() == "F":
        filters |= Q(farmer_id=number)
    return filters


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
        date_range = parse_inclusive_date_range(
            self.request.GET, label="parcel registration"
        )
        self.filter_date_error = date_range.error
        if query:
            queryset = queryset.filter(
                parcel_search_filter(query) | Q(farmer__barangay__icontains=query)
            )
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
        if not date_range.error:
            if date_range.start:
                queryset = queryset.filter(created_at__date__gte=date_range.start)
            if date_range.end:
                queryset = queryset.filter(created_at__date__lte=date_range.end)
        # Show every saved parcel by default, including inactive records, with
        # the most recently registered parcel first for immediate verification.
        return queryset.order_by("-created_at", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["barangays"] = (
            FarmParcel.objects.values_list("barangay", flat=True).distinct().order_by("barangay")
        )
        context["ownership_choices"] = FarmParcel._meta.get_field("ownership_type").choices
        context["filter_date_error"] = getattr(self, "filter_date_error", "")
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
        context["verification_count"] = parcels.exclude(coordinates="").filter(
            remarks__startswith="FMIS-DEMO-DATA:"
        ).count()
        context["rosario_map_bounds"] = ROSARIO_MAP_BOUNDS
        context["rosario_map_center"] = ROSARIO_MAP_CENTER
        context["rosario_boundary"] = ROSARIO_BOUNDARY
        context["rosario_barangays"] = ROSARIO_BARANGAYS
        context["pending_coordinate_reviews"] = ParcelCoordinateReview.objects.filter(
            status=ParcelCoordinateReview.STATUS_PENDING
        ).count()
        return context


class FarmParcelMapDataView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Return overview markers or actual-coordinate clusters on demand."""

    def get(self, request):
        requested_barangay = request.GET.get("barangay", "").strip()
        if requested_barangay and requested_barangay not in ROSARIO_BARANGAYS:
            return JsonResponse({"message": "Choose a valid Rosario barangay."}, status=400)
        requested_commodity = request.GET.get("commodity", "").strip()
        crop_records = CropRecord.objects.filter(is_active=True)
        if requested_barangay:
            crop_records = crop_records.filter(
                parcel__barangay=requested_barangay,
                parcel__is_active=True,
                parcel__farmer__is_active=True,
            )
        commodity_parcels = {}
        for crop_row in crop_records.values(
            "parcel_id", "crop_type"
        ).iterator(chunk_size=1000):
            group = commodity_group(crop_row["crop_type"])
            commodity_parcels.setdefault(group, set()).add(crop_row["parcel_id"])
        if (
            requested_commodity
            and requested_commodity not in commodity_parcels
            and not requested_barangay
        ):
            return JsonResponse({"message": "Choose a valid commodity."}, status=400)
        active_parcels = FarmParcel.objects.filter(
            is_active=True,
            farmer__is_active=True,
        )
        if requested_barangay:
            active_parcels = active_parcels.filter(barangay=requested_barangay)
        if requested_commodity:
            active_parcels = active_parcels.filter(
                pk__in=commodity_parcels.get(requested_commodity, set())
            )
        totals_by_barangay = dict(
            active_parcels.values("barangay")
            .annotate(total=Count("pk"))
            .values_list("barangay", "total")
        )
        coordinate_rows = active_parcels.values(
            "pk", "coordinates", "barangay", "remarks"
        ).iterator(chunk_size=1000)
        pending_review_ids = set(
            ParcelCoordinateReview.objects.filter(
                status=ParcelCoordinateReview.STATUS_PENDING,
                parcel__in=active_parcels,
            ).values_list("parcel_id", flat=True)
        )
        points_by_barangay = {}
        focus_candidates_by_barangay = {}
        mapped_by_barangay = {}
        verification_by_barangay = {}
        for row in coordinate_rows:
            pin_status = (
                "NEEDS_VERIFICATION"
                if row["pk"] in pending_review_ids
                else parcel_pin_status(row["coordinates"], row["remarks"])
            )
            if pin_status == "NEEDS_VERIFICATION":
                verification_by_barangay[row["barangay"]] = (
                    verification_by_barangay.get(row["barangay"], 0) + 1
                )
            point = FarmParcelMapView.parse_coordinates(row["coordinates"])
            # A syntactically valid saved coordinate is a map pin. Boundary and
            # verification findings remain available to the audit workflow, but
            # must not make a saved pin disappear from the operational map.
            if not point:
                continue
            points_by_barangay.setdefault(row["barangay"], []).append(
                {"id": row["pk"], "lat": point[0], "lng": point[1]}
            )
            reference_point = ROSARIO_BARANGAY_CENTERS.get(row["barangay"])
            is_reference_point = bool(
                reference_point
                and abs(point[0] - reference_point[0]) <= 0.00003
                and abs(point[1] - reference_point[1]) <= 0.00003
            )
            if pin_status == "PINNED" and not is_reference_point:
                focus_candidates_by_barangay.setdefault(row["barangay"], []).append(
                    {"id": row["pk"], "lat": point[0], "lng": point[1]}
                )
            mapped_by_barangay[row["barangay"]] = (
                mapped_by_barangay.get(row["barangay"], 0) + 1
            )
        total_count = sum(totals_by_barangay.values())
        barangay_counts = {
            barangay: {
                "total": total,
                "mapped": mapped_by_barangay.get(barangay, 0),
                "unmapped": max(0, total - mapped_by_barangay.get(barangay, 0)),
                "needs_verification": verification_by_barangay.get(barangay, 0),
            }
            for barangay, total in totals_by_barangay.items()
        }
        mapped_count = sum(mapped_by_barangay.values())
        payload = {
            "count": mapped_count,
            "unmapped_count": max(0, total_count - mapped_count),
            "verification_count": sum(verification_by_barangay.values()),
            "barangay_counts": barangay_counts,
            "commodities": sorted(commodity_parcels),
            "commodity": requested_commodity,
        }

        if not requested_barangay:
            barangay_markers = []
            for barangay in ROSARIO_BARANGAYS:
                points = points_by_barangay.get(barangay, [])
                reference_point = ROSARIO_BARANGAY_CENTERS.get(barangay)
                if not points and reference_point is None:
                    continue
                latitudes = [point["lat"] for point in points]
                longitudes = [point["lng"] for point in points]
                marker_point = reference_point or (
                    sum(latitudes) / len(latitudes),
                    sum(longitudes) / len(longitudes),
                )
                counts = barangay_counts.get(
                    barangay,
                    {"mapped": 0, "unmapped": 0, "needs_verification": 0},
                )
                barangay_markers.append(
                    {
                        "name": barangay,
                        "lat": marker_point[0],
                        "lng": marker_point[1],
                        "mapped": len(points),
                        "unmapped": counts["unmapped"],
                        "needs_verification": counts["needs_verification"],
                        "bounds": (
                            [
                                [min(latitudes), min(longitudes)],
                                [max(latitudes), max(longitudes)],
                            ]
                            if points
                            else [[marker_point[0], marker_point[1]], [marker_point[0], marker_point[1]]]
                        ),
                    }
                )
            payload.update(
                {
                    "mode": "overview",
                    "markers": [],
                    "clusters": [],
                    "barangays": barangay_markers,
                    "location_basis": "published_barangay_reference_points",
                }
            )
        else:
            focus_bounds = None
            focus_basis = "unavailable"
            candidates = focus_candidates_by_barangay.get(requested_barangay, [])
            coordinate_counts = Counter(
                (round(point["lat"], 7), round(point["lng"], 7))
                for point in candidates
            )
            reliable_points = [
                point
                for point in candidates
                if coordinate_counts[
                    (round(point["lat"], 7), round(point["lng"], 7))
                ]
                == 1
            ]
            if reliable_points:
                focus_bounds = [
                    [
                        min(point["lat"] for point in reliable_points),
                        min(point["lng"] for point in reliable_points),
                    ],
                    [
                        max(point["lat"] for point in reliable_points),
                        max(point["lng"] for point in reliable_points),
                    ],
                ]
                focus_basis = "non_flagged_parcel_coordinates"

            cluster_groups = {}
            for point in points_by_barangay.get(requested_barangay, []):
                key = parcel_cluster_key(point["lat"], point["lng"])
                cluster_groups.setdefault(key, []).append(point)
            clusters = []
            for key, points in sorted(cluster_groups.items()):
                latitudes = [point["lat"] for point in points]
                longitudes = [point["lng"] for point in points]
                clusters.append(
                    {
                        "id": key,
                        "lat": sum(latitudes) / len(latitudes),
                        "lng": sum(longitudes) / len(longitudes),
                        "count": len(points),
                        "bounds": [
                            [min(latitudes), min(longitudes)],
                            [max(latitudes), max(longitudes)],
                        ],
                    }
                )
            counts = barangay_counts.get(
                requested_barangay,
                {"total": 0, "mapped": 0, "unmapped": 0, "needs_verification": 0},
            )
            payload.update(
                {
                    "mode": "barangay",
                    "barangay": requested_barangay,
                    "count": counts["mapped"],
                    "unmapped_count": counts["unmapped"],
                    "verification_count": counts["needs_verification"],
                    "markers": [],
                    "barangays": [],
                    "clusters": clusters,
                    "focus_bounds": focus_bounds,
                    "focus_basis": focus_basis,
                    "focus_message": (
                        "The map view was kept unchanged because this barangay has no "
                        "authoritative boundary or reliable saved farm coordinates."
                        if not focus_bounds
                        else ""
                    ),
                }
            )
        response = JsonResponse(
            payload
        )
        patch_cache_control(response, no_store=True, private=True)
        return response


class FarmParcelMapParcelListView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Return one small, server-paginated parcel page for the map side panel."""

    def get(self, request):
        barangay = request.GET.get("barangay", "").strip()
        if barangay not in ROSARIO_BARANGAYS:
            return JsonResponse({"message": "Choose a barangay first."}, status=400)
        cluster_id = request.GET.get("cluster", "").strip()
        query = request.GET.get("q", "").strip()
        commodity = request.GET.get("commodity", "").strip()
        requested_status = request.GET.get("pin_status", "").strip().upper()
        if requested_status not in {"", "PINNED", "UNPINNED"}:
            return JsonResponse({"message": "Choose a valid pin status."}, status=400)
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except (TypeError, ValueError):
            page = 1

        parcels = FarmParcel.objects.filter(
            is_active=True,
            farmer__is_active=True,
            barangay=barangay,
        ).select_related("farmer")
        if commodity:
            matching_ids = [
                row["parcel_id"]
                for row in CropRecord.objects.filter(
                    is_active=True,
                    parcel__is_active=True,
                    parcel__farmer__is_active=True,
                    parcel__barangay=barangay,
                ).values("parcel_id", "crop_type")
                if commodity_group(row["crop_type"]) == commodity
            ]
            parcels = parcels.filter(pk__in=matching_ids)
        if query:
            parcels = parcels.filter(parcel_search_filter(query))

        rows = []
        for parcel in parcels.only(
            "pk", "parcel_name", "barangay", "coordinates", "created_at",
            "farmer__id", "farmer__first_name", "farmer__middle_name",
            "farmer__last_name", "farmer__extension_name",
        ).order_by("-created_at", "-pk"):
            point = FarmParcelMapView.parse_coordinates(parcel.coordinates)
            valid_point = point
            status = "PINNED" if valid_point else "UNPINNED"
            if requested_status and status != requested_status:
                continue
            if cluster_id:
                if not valid_point or parcel_cluster_key(*valid_point) != cluster_id:
                    continue
            rows.append((parcel, status, valid_point))

        total = len(rows)
        total_pages = max(1, (total + FARM_PARCEL_MAP_PAGE_SIZE - 1) // FARM_PARCEL_MAP_PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * FARM_PARCEL_MAP_PAGE_SIZE
        page_rows = rows[start : start + FARM_PARCEL_MAP_PAGE_SIZE]
        results = []
        for parcel, status, point in page_rows:
            results.append(
                {
                    "id": parcel.pk,
                    "farmer_id": parcel.farmer.record_id,
                    "farmer": parcel.farmer.full_name,
                    "parcel": parcel.display_name,
                    "barangay": parcel.barangay,
                    "pin_status": status,
                    "pin_status_label": status.replace("_", " ").title(),
                    "lat": point[0] if point else None,
                    "lng": point[1] if point else None,
                }
            )
        unlocated_matches = 0
        if query:
            unlocated_matches = sum(
                1
                for coordinates in parcels.values_list("coordinates", flat=True)
                if not FarmParcelMapView.parse_coordinates(coordinates)
            )
        response = JsonResponse(
            {
                "results": results,
                "pagination": {
                    "page": page,
                    "total_pages": total_pages,
                    "total": total,
                    "has_previous": page > 1,
                    "has_next": page < total_pages,
                },
                "barangay": barangay,
                "cluster": cluster_id,
                "page_size": FARM_PARCEL_MAP_PAGE_SIZE,
                "unlocated_matches": unlocated_matches,
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
                "pk", "area_hectares", "barangay", "coordinates", "remarks", "farmer__id",
                "farmer__first_name", "farmer__middle_name",
                "farmer__last_name", "farmer__extension_name",
            ),
            pk=pk,
        )
        active_photo = parcel.photos.filter(is_active=True).only("pk").first()
        crops = sorted(
            {
                commodity_group(crop_type)
                for crop_type in parcel.crops.filter(is_active=True).values_list(
                    "crop_type", flat=True
                )
            }
        )
        point = FarmParcelMapView.parse_coordinates(parcel.coordinates)
        pending = parcel.coordinate_reviews.filter(
            status=ParcelCoordinateReview.STATUS_PENDING
        ).first()
        pin_status = (
            "NEEDS_VERIFICATION"
            if pending
            else parcel_pin_status(parcel.coordinates, parcel.remarks)
        )
        return JsonResponse(
            {
                "id": parcel.pk,
                "farmer_id": parcel.farmer.record_id,
                "farmer": parcel.farmer.full_name,
                "parcel": parcel.display_name,
                "barangay": parcel.barangay,
                "area": f"{parcel.area_hectares} ha",
                "address": f"{parcel.barangay}, Rosario, Batangas",
                "coordinates": (
                    f"{point[0]:.7f}, {point[1]:.7f}" if point else "Not recorded"
                ),
                "pin_status": pin_status,
                "pin_status_label": pin_status.replace("_", " ").title(),
                "lat": point[0] if point else None,
                "lng": point[1] if point else None,
                "crops": [
                    {"name": name, "symbol": crop_symbol(name)} for name in crops
                ],
                "photo_url": (
                    reverse("farm_parcels:photo_view", args=[parcel.pk, active_photo.pk])
                    if active_photo
                    else ""
                ),
                "edit_url": reverse("farm_parcels:detail", args=[parcel.pk]),
                "pending_review": coordinate_review_payload(pending),
            }
        )


class FarmParcelMapSearchView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    """Search parcels without placing every record in a large HTML select."""

    def get(self, request):
        query = request.GET.get("q", "").strip()
        barangay = request.GET.get("barangay", "").strip()
        requested_commodity = request.GET.get("commodity", "").strip()
        requested_status = request.GET.get("pin_status", "").strip().upper()
        compact = request.GET.get("compact") == "1"
        pinned_only = request.GET.get("pinned_only") == "1"
        parcels = FarmParcel.objects.filter(
            is_active=True,
            farmer__is_active=True,
        ).select_related("farmer")
        if barangay in ROSARIO_BARANGAYS:
            parcels = parcels.filter(barangay=barangay)
        if requested_commodity:
            commodity_parcel_ids = {
                row["parcel_id"]
                for row in CropRecord.objects.filter(
                    is_active=True,
                    parcel__is_active=True,
                    parcel__farmer__is_active=True,
                ).values("parcel_id", "crop_type").iterator(chunk_size=1000)
                if commodity_group(row["crop_type"]) == requested_commodity
            }
            parcels = parcels.filter(pk__in=commodity_parcel_ids)
        pending_review_ids = set(
            ParcelCoordinateReview.objects.filter(
                status=ParcelCoordinateReview.STATUS_PENDING,
                parcel__in=parcels,
            ).values_list("parcel_id", flat=True)
        )
        count_cache_key = (
            f"farm-parcel-pin-counts:{barangay or 'all'}:"
            f"{requested_commodity or 'all'}"
        )
        status_counts = {} if compact else cache.get(count_cache_key)
        if not compact and status_counts is None:
            status_counts = {
                "ALL": 0,
                "PINNED": 0,
                "UNPINNED": 0,
                "NEEDS_VERIFICATION": 0,
            }
            for coordinate_row in parcels.values("pk", "coordinates", "remarks").iterator(chunk_size=1000):
                status = (
                    "NEEDS_VERIFICATION"
                    if coordinate_row["pk"] in pending_review_ids
                    else parcel_pin_status(coordinate_row["coordinates"], coordinate_row["remarks"])
                )
                status_counts["ALL"] += 1
                status_counts[status] += 1
            cache.set(count_cache_key, status_counts, 30)
        if query:
            parcels = parcels.filter(parcel_search_filter(query))
        # Put parcels requiring field work first so staff do not have to guess
        # which records still need a location. The final validity check below
        # also catches malformed/out-of-bound legacy coordinate strings.
        if requested_status == "UNPINNED":
            parcels = parcels.filter(Q(coordinates="") | Q(coordinates__isnull=True)).exclude(
                pk__in=pending_review_ids
            )
        elif requested_status == "PINNED":
            parcels = parcels.exclude(coordinates="").exclude(
                remarks__startswith="FMIS-DEMO-DATA:"
            ).exclude(pk__in=pending_review_ids)
        elif requested_status == "NEEDS_VERIFICATION":
            parcels = parcels.filter(
                Q(pk__in=pending_review_ids)
                | ~Q(coordinates="")
            )

        parcels = parcels.annotate(
            pin_order=Case(
                When(Q(coordinates="") | Q(coordinates__isnull=True), then=Value(0)),
                When(remarks__startswith="FMIS-DEMO-DATA:", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by("pin_order", "-created_at", "-pk")[:400]
        results = []
        unlocated_matches = 0
        for parcel in parcels:
            pin_status = (
                "NEEDS_VERIFICATION"
                if parcel.pk in pending_review_ids
                else parcel_pin_status(parcel.coordinates, parcel.remarks)
            )
            if requested_status and pin_status != requested_status:
                continue
            point = FarmParcelMapView.parse_coordinates(parcel.coordinates)
            is_pinned = point is not None
            if pinned_only and not is_pinned:
                unlocated_matches += 1
                continue
            status_label = pin_status.replace("_", " ")
            response_pin_status = "PINNED" if pinned_only and is_pinned else pin_status
            response_status_label = "PINNED" if pinned_only and is_pinned else status_label
            results.append(
                {
                    "id": parcel.pk,
                    "parcel": parcel.display_name,
                    "farmer": parcel.farmer.full_name,
                    "farmer_id": parcel.farmer.record_id,
                    "label": (
                        f"{status_label} — {parcel.farmer.record_id} — "
                        f"{parcel.farmer.full_name} / {parcel.display_name} "
                        f"({parcel.barangay})"
                    ),
                    "is_pinned": is_pinned,
                    "pin_status": response_pin_status,
                    "pin_status_label": response_status_label,
                    "barangay": parcel.barangay,
                    "livelihood": parcel.farmer.get_livelihood_display(),
                    "livelihood_code": parcel.farmer.livelihood,
                    "activities": parcel.farmer.activities,
                    "activities_display": parcel.farmer.activities_display,
                }
            )
        status_order = {"UNPINNED": 0, "NEEDS_VERIFICATION": 1, "PINNED": 2}
        results.sort(key=lambda result: (status_order[result["pin_status"]], result["label"]))
        results = results[:40]
        return JsonResponse(
            {
                "results": results,
                "counts": status_counts,
                "unlocated_matches": unlocated_matches,
            }
        )


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
            review = propose_coordinate_change(
                parcel=parcel,
                actor=request.user,
                operation=ParcelCoordinateReview.OPERATION_REMOVE,
                issue_codes=["staff_reported_incorrect"],
                notes="Requested removal of an incorrect or no longer applicable pin.",
            )
            record_request_event(
                request,
                title="Farm Parcel Coordinate Review Submitted",
                module="Farm Parcels",
                description=f"{request.user.display_name} submitted a map-pin removal for review.",
                target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
                reason="The existing pin remains unchanged until an authorized staff member approves the proposal.",
                details=[{
                    "field": "Farm parcel coordinates",
                    "before": parcel.coordinates.strip() or "Not previously pinned",
                    "after": "Proposed: Not pinned",
                }],
            )
            return JsonResponse(
                {
                    "ok": True,
                    "pending": True,
                    "review_id": review.pk,
                    "message": f"{parcel.display_name}'s pin removal is awaiting approval.",
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
        new_coordinates = format_coordinates(latitude, longitude)
        if operation == "move":
            try:
                review, history = apply_coordinate_change_immediately(
                    parcel=parcel,
                    actor=request.user,
                    proposed_coordinates=new_coordinates,
                    notes=request.POST.get("notes", "").strip(),
                )
            except ValidationError as error:
                return JsonResponse(
                    {"ok": False, "message": error.messages[0]},
                    status=400,
                )
            return JsonResponse(
                {
                    "ok": True,
                    "pending": False,
                    "review_id": review.pk,
                    "history_id": history.pk,
                    "message": f"{parcel.display_name}'s location was updated successfully.",
                }
            )
        try:
            review = propose_coordinate_change(
                parcel=parcel,
                actor=request.user,
                operation=ParcelCoordinateReview.OPERATION_SET,
                proposed_coordinates=new_coordinates,
                issue_codes=["staff_map_correction" if previous_coordinates else "missing"],
                notes=request.POST.get("notes", "").strip(),
            )
        except ValidationError as error:
            return JsonResponse(
                {"ok": False, "message": error.messages[0]},
                status=400,
            )
        record_request_event(
            request,
            title="Farm Parcel Coordinate Review Submitted",
            module="Farm Parcels",
            description=f"{request.user.display_name} submitted a farm parcel coordinate for review.",
            target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
            reason="The saved coordinate remains unchanged until this proposal is approved.",
            details=[{
                "field": "Farm parcel coordinates",
                "before": previous_coordinates or "Not previously pinned",
                "after": new_coordinates,
            }],
        )
        return JsonResponse(
            {
                "ok": True,
                "pending": True,
                "review_id": review.pk,
                "message": f"{parcel.display_name}'s proposed location is awaiting approval.",
            }
        )


def coordinate_review_payload(review):
    if review is None:
        return None
    return {
        "id": review.pk,
        "operation": review.operation,
        "original_coordinates": review.original_coordinates or "Not pinned",
        "proposed_coordinates": review.proposed_coordinates or "Not pinned",
        "evidence_source": review.evidence_source,
        "notes": review.staff_notes,
        "approve_url": reverse("farm_parcels:coordinate_review_approve", args=[review.pk]),
        "reject_url": reverse("farm_parcels:coordinate_review_reject", args=[review.pk]),
    }


class CoordinateVerificationListView(
    FMISLoginRequiredMixin, StaffRequiredMixin, RoleAwareParcelMixin, TemplateView
):
    template_name = "farm_parcels/coordinate_verification.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["pending_reviews"] = (
            ParcelCoordinateReview.objects.filter(status=ParcelCoordinateReview.STATUS_PENDING)
            .select_related("parcel", "submitted_by")[:200]
        )
        context["coordinate_history"] = (
            ParcelCoordinateHistory.objects.select_related("parcel", "changed_by", "review")[:100]
        )
        return context


class CoordinateReviewDecisionView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    decision = ""

    def post(self, request, pk):
        try:
            if self.decision == "approve":
                review, history = approve_coordinate_review(
                    review_id=pk,
                    actor=request.user,
                    decision_notes=request.POST.get("decision_notes", "").strip(),
                )
                return JsonResponse(
                    {
                        "ok": True,
                        "parcel_id": review.parcel_id,
                        "history_id": history.pk,
                        "message": "Coordinate change approved and the map record was refreshed.",
                    }
                )
            review = reject_coordinate_review(
                review_id=pk,
                actor=request.user,
                decision_notes=request.POST.get("decision_notes", "").strip(),
            )
            return JsonResponse(
                {"ok": True, "parcel_id": review.parcel_id, "message": "Coordinate proposal rejected."}
            )
        except (ParcelCoordinateReview.DoesNotExist, ValidationError) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else "Coordinate proposal not found."
            return JsonResponse({"ok": False, "message": message}, status=409)


class CoordinateReviewApproveView(CoordinateReviewDecisionView):
    decision = "approve"


class CoordinateReviewRejectView(CoordinateReviewDecisionView):
    decision = "reject"


class CoordinateHistoryReverseView(FMISLoginRequiredMixin, StaffRequiredMixin, View):
    def post(self, request, pk):
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return JsonResponse({"ok": False, "message": "Enter a reason for the reversal."}, status=400)
        try:
            reversal = reverse_coordinate_history(history_id=pk, actor=request.user, reason=reason)
        except (ParcelCoordinateHistory.DoesNotExist, ValidationError) as error:
            message = error.messages[0] if isinstance(error, ValidationError) else "Coordinate history not found."
            return JsonResponse({"ok": False, "message": message}, status=409)
        return JsonResponse(
            {"ok": True, "parcel_id": reversal.parcel_id, "message": "Coordinate change safely reversed."}
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
                "Choose one or more valid field photos.",
            )
            messages.error(request, error)
            return redirect("farm_parcels:detail", pk=parcel.pk)

        uploads = form.cleaned_data["field_photo"]
        with transaction.atomic():
            locked_parcel = FarmParcel.objects.select_for_update().get(pk=parcel.pk)
            for upload in uploads:
                FarmParcelPhoto.objects.create(
                    parcel=locked_parcel,
                    image=upload,
                    uploaded_by=request.user,
                )
            record_request_event(
                request,
                title="Farm Parcel Photos Added",
                module="Farm Parcels",
                description=f"{request.user.display_name} added {len(uploads)} office field photo(s).",
                target_label=f"{parcel.farmer.record_id} - {parcel.display_name}",
                reason="Office field documentation for parcel review and decision-making.",
                details=[
                    {
                        "field": "Field photo gallery",
                        "before": "Existing gallery retained",
                        "after": f"{len(uploads)} photo(s) added",
                    }
                ],
            )
        messages.success(request, f"{len(uploads)} field photo(s) were uploaded.")
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
