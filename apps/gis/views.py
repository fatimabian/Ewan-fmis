"""Staff-only GIS pages and on-demand map data."""

from dataclasses import asdict

from django.http import Http404, JsonResponse
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.common.constants import ROSARIO_BARANGAYS
from apps.common.mixins import FMISLoginRequiredMixin
from apps.common.permissions import StaffRequiredMixin
from apps.farm_parcels.demo_locations import ROSARIO_BARANGAY_CENTERS
from apps.farm_parcels.models import RosarioBarangayBoundary
from apps.farm_parcels.rosario_boundary import ROSARIO_BOUNDARY

from . import layers

MAX_POINTS = 1500


class GISAccessMixin(FMISLoginRequiredMixin, StaffRequiredMixin):
    """The GIS map shows personal locations, so it follows the staff-only rule of the parcel map."""

    denied_message = "The GIS map is available to staff accounts only."


class GISMapView(GISAccessMixin, TemplateView):
    template_name = "gis/map.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        specs = layers.filter_specs()
        config = {
            "layers": [asdict(layer) for layer in layers.LAYERS.values()],
            "filterSpecs": specs,
            "barangays": list(ROSARIO_BARANGAYS),
            "commodities": layers.COMMODITY_GROUPS,
            "boundary": [list(point) for point in ROSARIO_BOUNDARY],
            "centers": {name: list(point) for name, point in ROSARIO_BARANGAY_CENTERS.items()},
            "dataUrl": reverse("gis:data"),
            "pinUrl": reverse("farm_parcels:pin_farmer"),
            "detailUrl": reverse("gis:detail"),
            "parcelListUrl": reverse("farm_parcels:map_parcels"),
            "parcelDetailUrl": reverse("farm_parcels:map_detail", args=[0]).replace("/0/", "/{id}/"),
        }
        context.update(base_template="base/staff_base.html", config=config, layer_list=list(layers.LAYERS.values()))
        return context


class GISDataView(GISAccessMixin, View):
    """Level one (density grid) or level two (individual points) for the chosen layer."""

    def get(self, request):
        params, error = layers.parse_params(request.GET)
        if error:
            return JsonResponse({"message": error}, status=400)
        layer = layers.LAYERS[params.layer]
        found = layers.records(params)
        mapped = [record for record in found if record.point]
        payload = {
            "layer": params.layer,
            "total": len(found),
            "mapped": len(mapped),
            "unmapped": len(found) - len(mapped),
            "attention": sum(1 for record in found if record.status == layers.ATTENTION),
            "level": 2 if params.barangay else 1,
            "insights": layers.insights(found, layer),
        }
        if params.barangay:
            payload["truncated"] = len(mapped) > MAX_POINTS
            payload["points"] = [
                {"id": r.pk, "lat": r.point[0], "lng": r.point[1], "status": r.status}
                for r in mapped[:MAX_POINTS]
            ]
            boundary = RosarioBarangayBoundary.objects.filter(is_active=True, barangay_name=params.barangay).first()
            payload["barangay_geometry"] = boundary.geometry if boundary else None
        else:
            payload.update(layers.grid(mapped))
        return JsonResponse(payload)


class GISDetailView(GISAccessMixin, View):
    """Level three: a short card for one clicked record."""

    def get(self, request):
        layer = request.GET.get("layer", "")
        try:
            pk = int(request.GET.get("id", ""))
        except ValueError:
            raise Http404
        if layer not in layers.LAYERS:
            raise Http404
        card = layers.detail(layer, pk)
        if card is None:
            raise Http404
        return JsonResponse(card)
