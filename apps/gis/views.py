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
        config = {
            "layers": [asdict(layer) for layer in layers.LAYERS.values()],
            "barangays": list(ROSARIO_BARANGAYS),
            "commodities": layers.COMMODITY_GROUPS,
            "boundary": [list(point) for point in ROSARIO_BOUNDARY],
            "centers": {name: list(point) for name, point in ROSARIO_BARANGAY_CENTERS.items()},
            "dataUrl": reverse("gis:data"),
            "detailUrl": reverse("gis:detail"),
        }
        context.update(base_template="base/staff_base.html", config=config, layer_list=list(layers.LAYERS.values()))
        return context


def read_filters(request):
    """Validate the query string; return (filters, error message)."""
    layer = request.GET.get("layer", "parcels")
    barangay = request.GET.get("barangay", "")
    commodity = request.GET.get("commodity", "")
    status = request.GET.get("status", "")
    if layer not in layers.LAYERS:
        return None, "Choose a valid layer."
    if barangay and barangay not in ROSARIO_BARANGAYS:
        return None, "Choose a valid Rosario barangay."
    if commodity and commodity not in layers.COMMODITY_GROUPS:
        return None, "Choose a valid commodity."
    if status not in {value for value, _ in layers.LAYERS[layer].status_options} | {""}:
        return None, "Choose a valid status."
    return {"layer": layer, "barangay": barangay, "commodity": commodity if layers.LAYERS[layer].uses_commodity else "", "status": status}, None


class GISDataView(GISAccessMixin, View):
    """Level one (barangay totals) or level two (individual points) for the chosen layer."""

    def get(self, request):
        filters, error = read_filters(request)
        if error:
            return JsonResponse({"message": error}, status=400)
        found = layers.records(**filters)
        mapped = [record for record in found if record.point]
        payload = {
            "layer": filters["layer"],
            "total": len(found),
            "mapped": len(mapped),
            "unmapped": len(found) - len(mapped),
            "attention": sum(1 for record in found if record.status == layers.ATTENTION),
            "level": 2 if filters["barangay"] else 1,
        }
        if filters["barangay"]:
            payload["truncated"] = len(mapped) > MAX_POINTS
            payload["points"] = [
                {"id": r.pk, "lat": r.point[0], "lng": r.point[1], "status": r.status}
                for r in mapped[:MAX_POINTS]
            ]
            boundary = RosarioBarangayBoundary.objects.filter(is_active=True, barangay_name=filters["barangay"]).first()
            payload["barangay_geometry"] = boundary.geometry if boundary else None
        else:
            totals = {}
            for record in mapped:
                bucket = totals.setdefault(record.barangay, {"count": 0, "attention": 0})
                bucket["count"] += 1
                bucket["attention"] += record.status == layers.ATTENTION
            payload["bubbles"] = [
                {"barangay": name, "lat": ROSARIO_BARANGAY_CENTERS[name][0], "lng": ROSARIO_BARANGAY_CENTERS[name][1], **counts}
                for name, counts in sorted(totals.items())
                if name in ROSARIO_BARANGAY_CENTERS
            ]
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
