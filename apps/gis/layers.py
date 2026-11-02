"""What each GIS map layer shows. Layers return plain records; views shape them for the browser."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.urls import reverse

from apps.common.constants import COMMODITY_DETAIL_TO_GROUP, ROSARIO_BARANGAYS, commodity_group
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel, ParcelCoordinateReview
from apps.farm_parcels.views import FarmParcelMapView, parcel_pin_status
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest

# The three status colours used on every layer.
GOOD, ATTENTION, NEUTRAL = "good", "attention", "neutral"
ALL, ATTENTION_ONLY = "", "attention"
OPEN_REQUESTS = ("PENDING", "IN_PROGRESS")
COMMODITY_GROUPS = sorted(set(COMMODITY_DETAIL_TO_GROUP.values()) | {"Other Commodity"})


@dataclass(frozen=True)
class Record:
    pk: int
    barangay: str
    point: tuple | None
    status: str
    facet: tuple = ("", "")  # (value, label) used for the breakdown list and one click filtering


@dataclass(frozen=True)
class Layer:
    key: str
    label: str
    icon: str
    legend: tuple  # at most three (status, label) pairs
    status_options: tuple  # (value, label)
    uses_commodity: bool
    filters: tuple  # extra filter keys offered under "More filters"
    facet_title: str
    facet_filter: str  # the filter a click on the breakdown sets


ATTENTION_OPTIONS = ((ALL, "Everything"), (ATTENTION_ONLY, "Needs attention only"))
RANGE_FARMER = ("farmer_from", "farmer_to")
LAYERS = {
    layer.key: layer
    for layer in (
        Layer("farmers", "Farmers", "bi-person-fill",
              ((GOOD, "Registration completed"), (ATTENTION, "Registration not completed")),
              ATTENTION_OPTIONS, True, (*RANGE_FARMER, "livelihood", "sex", "group"), "By livelihood", "livelihood"),
        Layer("parcels", "Farm parcels", "bi-pentagon-fill",
              ((GOOD, "Pin verified"), (ATTENTION, "Pin needs verification")),
              ATTENTION_OPTIONS, True, (*RANGE_FARMER, "ownership", "farm_type", "land_type", "area_min", "area_max"),
              "By ownership", "ownership"),
        Layer("commodities", "Commodities", "bi-tree-fill",
              ((GOOD, "Pin verified"), (ATTENTION, "Pin needs verification")),
              ATTENTION_OPTIONS, True, (*RANGE_FARMER, "organic", "area_min", "area_max"), "By commodity", "commodity"),
        Layer("requests", "Service requests", "bi-clipboard-check-fill",
              ((ATTENTION, "Pending"), (NEUTRAL, "In progress"), (GOOD, "Completed")),
              (("open", "Open requests"), ("PENDING", "Pending only"),
               ("IN_PROGRESS", "In progress only"), ("COMPLETED", "Completed")), False,
              (*RANGE_FARMER, "service", "priority", "date_from", "date_to"), "By service type", "service"),
        Layer("interventions", "Interventions", "bi-box2-heart-fill",
              ((ATTENTION, "Pending"), (GOOD, "Received"), (NEUTRAL, "Declined or no-show")),
              ((ALL, "Everything"), ("PENDING", "Pending"), ("RECEIVED", "Received"), ("OTHER", "Declined or no-show")),
              False, (*RANGE_FARMER, "kind", "date_from", "date_to"), "By assistance type", "kind"),
    )
}

# Every extra filter: label, input kind and (for selects) the allowed values.
FILTER_SPECS = {
    "farmer_from": {"label": "Farmer no. from", "kind": "number", "hint": "F-0001 = 1"},
    "farmer_to": {"label": "Farmer no. to", "kind": "number", "hint": ""},
    "livelihood": {"label": "Livelihood", "kind": "select", "options": list(Farmer.LIVELIHOOD_CHOICES)},
    "sex": {"label": "Sex", "kind": "select", "options": list(Farmer.SEX_CHOICES)},
    "group": {"label": "Special group", "kind": "select", "options": [
        ("pwd", "Person with disability"), ("four_ps", "4Ps member"),
        ("indigenous", "Indigenous people"), ("association", "Association member")]},
    "ownership": {"label": "Ownership", "kind": "select", "options": list(FarmParcel.OWNERSHIP_CHOICES)},
    "farm_type": {"label": "Farm type", "kind": "select", "options": list(FarmParcel.FARM_TYPE_CHOICES)},
    "land_type": {"label": "Land type", "kind": "select", "options": list(FarmParcel.LAND_TYPE_CHOICES)},
    "area_min": {"label": "Area from (ha)", "kind": "number", "hint": ""},
    "area_max": {"label": "Area to (ha)", "kind": "number", "hint": ""},
    "organic": {"label": "Organic", "kind": "select", "options": [("yes", "Organic"), ("no", "Not organic")]},
    "service": {"label": "Service type", "kind": "select", "options": []},  # filled from the catalog
    "priority": {"label": "Priority", "kind": "select", "options": list(ServiceRequest.PRIORITY_CHOICES)},
    "kind": {"label": "Assistance type", "kind": "select", "options": list(Intervention.TYPE_CHOICES)},
    "date_from": {"label": "From date", "kind": "date", "hint": ""},
    "date_to": {"label": "To date", "kind": "date", "hint": ""},
}


def filter_specs():
    """Filter specs with the service types read from the catalog."""
    specs = {key: dict(spec) for key, spec in FILTER_SPECS.items()}
    categories = sorted(set(ServiceCatalog.objects.filter(is_active=True).values_list("category", flat=True)))
    specs["service"]["options"] = [(name, name) for name in categories]
    return specs


@dataclass(frozen=True)
class Params:
    """Validated filters for one request."""

    layer: str
    barangay: str = ""
    commodity: str = ""
    status: str = ""
    extra: dict = field(default_factory=dict)  # key -> int, Decimal, date or str


def parse_params(query, specs=None):
    """Validate the query string. Returns (Params, error message)."""
    specs = specs or filter_specs()
    layer_key = query.get("layer", "parcels")
    if layer_key not in LAYERS:
        return None, "Choose a valid layer."
    layer = LAYERS[layer_key]
    barangay, commodity, status = query.get("barangay", ""), query.get("commodity", ""), query.get("status", "")
    if barangay and barangay not in ROSARIO_BARANGAYS:
        return None, "Choose a valid Rosario barangay."
    if commodity and commodity not in COMMODITY_GROUPS:
        return None, "Choose a valid commodity."
    if status not in {value for value, _ in layer.status_options} | {""}:
        return None, "Choose a valid status."
    extra = {}
    for key in layer.filters:
        raw = (query.get(key) or "").strip()
        if not raw:
            continue
        spec = specs[key]
        try:
            if spec["kind"] == "select":
                if raw not in {value for value, _ in spec["options"]}:
                    return None, f"Choose a valid {spec['label'].lower()}."
                extra[key] = raw
            elif spec["kind"] == "date":
                extra[key] = date.fromisoformat(raw)
            elif key.startswith("farmer"):
                extra[key] = int(raw)
                if extra[key] < 1:
                    raise ValueError
            else:
                extra[key] = Decimal(raw)
                if extra[key] < 0:
                    raise ValueError
        except (ValueError, InvalidOperation):
            return None, f"Enter a valid value for {spec['label'].lower()}."
    for low, high in (("farmer_from", "farmer_to"), ("area_min", "area_max"), ("date_from", "date_to")):
        if low in extra and high in extra and extra[low] > extra[high]:
            return None, f"{FILTER_SPECS[low]['label']} must not be after {FILTER_SPECS[high]['label'].lower()}."
    return Params(layer_key, barangay, commodity if layer.uses_commodity else "", status, extra), None


def parse_point(text):
    return FarmParcelMapView.parse_coordinates(text) if (text or "").strip() else None


def _pending_reviews():
    """Parcel ids whose pin is waiting for a coordinate review."""
    return set(
        ParcelCoordinateReview.objects.filter(status=ParcelCoordinateReview.STATUS_PENDING)
        .values_list("parcel_id", flat=True)
    )


def _status_of_pin(pk, coordinates, remarks, pending):
    verdict = "NEEDS_VERIFICATION" if pk in pending else parcel_pin_status(coordinates, remarks)
    return ATTENTION if verdict == "NEEDS_VERIFICATION" else GOOD


def _commodity_parcel_ids(commodity):
    """Parcel ids that record an active commodity in the given group."""
    return {
        parcel_id
        for parcel_id, crop_type in CropRecord.objects.filter(is_active=True).values_list("parcel_id", "crop_type")
        if commodity_group(crop_type) == commodity
    }


def _farmer_points(farmer_ids):
    """Farmer id -> point: the farmer's own pin, else the first mapped parcel."""
    points = {}
    for pk, text in Farmer.objects.filter(pk__in=farmer_ids).values_list("pk", "location_coordinates"):
        if point := parse_point(text):
            points[pk] = point
    parcels = (
        FarmParcel.objects.filter(is_active=True, farmer_id__in=farmer_ids).exclude(coordinates="")
        .order_by("pk").values_list("farmer_id", "coordinates")
    )
    for farmer_id, text in parcels:
        if farmer_id not in points and (point := parse_point(text)):
            points[farmer_id] = point
    return points


def _in_farmer_range(queryset, params, field_name):
    """Apply the farmer number range (F-0001 is farmer 1) to a queryset."""
    if "farmer_from" in params.extra:
        queryset = queryset.filter(**{f"{field_name}__gte": params.extra["farmer_from"]})
    if "farmer_to" in params.extra:
        queryset = queryset.filter(**{f"{field_name}__lte": params.extra["farmer_to"]})
    return queryset


def _in_area_range(queryset, params, field_name):
    if "area_min" in params.extra:
        queryset = queryset.filter(**{f"{field_name}__gte": params.extra["area_min"]})
    if "area_max" in params.extra:
        queryset = queryset.filter(**{f"{field_name}__lte": params.extra["area_max"]})
    return queryset


def _parcel_records(params):
    parcels = FarmParcel.objects.filter(is_active=True, farmer__is_active=True)
    if params.barangay:
        parcels = parcels.filter(barangay=params.barangay)
    if params.commodity:
        parcels = parcels.filter(pk__in=_commodity_parcel_ids(params.commodity))
    for key in ("ownership", "farm_type", "land_type"):
        if key in params.extra:
            parcels = parcels.filter(**{f"{'ownership_type' if key == 'ownership' else key}": params.extra[key]})
    parcels = _in_area_range(_in_farmer_range(parcels, params, "farmer_id"), params, "area_hectares")
    pending = _pending_reviews()
    labels = dict(FarmParcel.OWNERSHIP_CHOICES)
    rows = parcels.values_list("pk", "barangay", "coordinates", "remarks", "ownership_type")
    return [
        Record(pk, bgy, parse_point(text), _status_of_pin(pk, text, remarks, pending), (own, labels.get(own, own)))
        for pk, bgy, text, remarks, own in rows
    ]


def _commodity_records(params):
    crops = CropRecord.objects.filter(is_active=True, parcel__is_active=True, parcel__farmer__is_active=True)
    if params.barangay:
        crops = crops.filter(parcel__barangay=params.barangay)
    if "organic" in params.extra:
        crops = crops.filter(is_organic=params.extra["organic"] == "yes")
    crops = _in_area_range(_in_farmer_range(crops, params, "parcel__farmer_id"), params, "area_hectares")
    pending = _pending_reviews()
    rows = crops.values_list("pk", "crop_type", "parcel_id", "parcel__barangay", "parcel__coordinates", "parcel__remarks")
    records = []
    for pk, crop_type, parcel_id, bgy, text, remarks in rows:
        group = commodity_group(crop_type)
        if params.commodity and group != params.commodity:
            continue
        records.append(Record(pk, bgy, parse_point(text), _status_of_pin(parcel_id, text, remarks, pending), (group, group)))
    return records


def _farmer_records(params):
    farmers = Farmer.objects.filter(is_active=True)
    if params.barangay:
        farmers = farmers.filter(barangay=params.barangay)
    if params.commodity:
        owners = FarmParcel.objects.filter(pk__in=_commodity_parcel_ids(params.commodity)).values_list("farmer_id", flat=True)
        farmers = farmers.filter(pk__in=list(owners))
    for key in ("livelihood", "sex"):
        if key in params.extra:
            farmers = farmers.filter(**{key: params.extra[key]})
    flag = {"pwd": "is_pwd", "four_ps": "is_four_ps", "indigenous": "is_indigenous", "association": "is_association_member"}
    if "group" in params.extra:
        farmers = farmers.filter(**{flag[params.extra["group"]]: True})
    farmers = _in_farmer_range(farmers, params, "pk")
    rows = list(farmers.values_list("pk", "barangay", "registration_status", "livelihood"))
    points = _farmer_points([row[0] for row in rows])
    labels = dict(Farmer.LIVELIHOOD_CHOICES)
    return [
        Record(pk, bgy, points.get(pk), GOOD if registration == "COMPLETED" else ATTENTION, (livelihood, labels.get(livelihood, livelihood)))
        for pk, bgy, registration, livelihood in rows
    ]


REQUEST_STATUS = {"PENDING": ATTENTION, "IN_PROGRESS": NEUTRAL, "COMPLETED": GOOD}


def _request_records(params):
    requests = ServiceRequest.objects.filter(scope="INDIVIDUAL", farmer__is_active=True)
    requests = requests.filter(status__in=OPEN_REQUESTS if params.status in ("", "open") else [params.status])
    if params.barangay:
        requests = requests.filter(farmer__barangay=params.barangay)
    if "service" in params.extra:
        requests = requests.filter(service__category=params.extra["service"])
    if "priority" in params.extra:
        requests = requests.filter(priority=params.extra["priority"])
    if "date_from" in params.extra:
        requests = requests.filter(created_at__date__gte=params.extra["date_from"])
    if "date_to" in params.extra:
        requests = requests.filter(created_at__date__lte=params.extra["date_to"])
    requests = _in_farmer_range(requests, params, "farmer_id")
    rows = list(requests.values_list("pk", "status", "farmer_id", "farmer__barangay", "service__category"))
    points = _farmer_points({row[2] for row in rows})
    return [
        Record(pk, bgy, points.get(farmer_id), REQUEST_STATUS[state], (category, category))
        for pk, state, farmer_id, bgy, category in rows
    ]


RECIPIENT_STATUS = {"PENDING": ATTENTION, "RECEIVED": GOOD, "DECLINED": NEUTRAL, "NO_SHOW": NEUTRAL}


def _intervention_records(params):
    recipients = InterventionRecipient.objects.filter(
        is_active=True, farmer__is_active=True,
        intervention__status__in=["SCHEDULED", "ONGOING", "COMPLETED"],
    )
    if params.status == "OTHER":
        recipients = recipients.filter(status__in=["DECLINED", "NO_SHOW"])
    elif params.status:
        recipients = recipients.filter(status=params.status)
    if params.barangay:
        recipients = recipients.filter(farmer__barangay=params.barangay)
    if "kind" in params.extra:
        recipients = recipients.filter(intervention__intervention_type=params.extra["kind"])
    if "date_from" in params.extra:
        recipients = recipients.filter(intervention__intervention_date__gte=params.extra["date_from"])
    if "date_to" in params.extra:
        recipients = recipients.filter(intervention__intervention_date__lte=params.extra["date_to"])
    recipients = _in_farmer_range(recipients, params, "farmer_id")
    rows = list(recipients.values_list("pk", "status", "farmer_id", "farmer__barangay", "intervention__intervention_type"))
    points = _farmer_points({row[2] for row in rows})
    labels = dict(Intervention.TYPE_CHOICES)
    return [
        Record(pk, bgy, points.get(farmer_id), RECIPIENT_STATUS[state], (kind, labels.get(kind, kind)))
        for pk, state, farmer_id, bgy, kind in rows
    ]


def records(params):
    """All records of a layer matching the filters, mapped or not."""
    builders = {
        "parcels": _parcel_records, "commodities": _commodity_records, "farmers": _farmer_records,
        "requests": _request_records, "interventions": _intervention_records,
    }
    found = builders[params.layer](params)
    if params.status == ATTENTION_ONLY:
        found = [record for record in found if record.status == ATTENTION]
    return found


def insights(found, layer, top=5):
    """Short ranked lists for the side panel."""
    by_barangay = Counter(record.barangay for record in found)
    attention = Counter(record.barangay for record in found if record.status == ATTENTION)
    facet = Counter(record.facet for record in found if record.facet[0])
    rank = lambda counter: sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))[:top]
    return {
        "busiest": [{"barangay": name, "count": count} for name, count in rank(by_barangay)],
        "attention": [{"barangay": name, "count": count} for name, count in rank(attention)],
        "facet": {
            "title": layer.facet_title, "filter": layer.facet_filter,
            "items": [{"value": value, "label": label, "count": count} for (value, label), count in rank(facet)],
        },
    }


def grid(mapped, size=0.01):
    """Group mapped records into square cells (about 1 km) with three density tiers."""
    cells = {}
    for record in mapped:
        key = (int(record.point[0] // size), int(record.point[1] // size))
        cell = cells.setdefault(key, {"count": 0, "attention": 0, "barangays": Counter()})
        cell["count"] += 1
        cell["attention"] += record.status == ATTENTION
        cell["barangays"][record.barangay] += 1
    counts = sorted(cell["count"] for cell in cells.values())
    low = counts[len(counts) // 3] if counts else 0
    high = counts[(2 * len(counts)) // 3] if counts else 0
    out, spans = [], {1: [], 2: [], 3: []}
    for (row, column), cell in sorted(cells.items()):
        tier = 1 if cell["count"] <= low else 2 if cell["count"] <= high else 3
        spans[tier].append(cell["count"])
        out.append({
            "lat": round(row * size, 5), "lng": round(column * size, 5), "count": cell["count"],
            "attention": cell["attention"], "tier": tier,
            "barangay": cell["barangays"].most_common(1)[0][0],
        })
    tiers = [
        {"tier": tier, "label": f"{min(values)}" if min(values) == max(values) else f"{min(values)} to {max(values)}"}
        for tier, values in spans.items() if values
    ]
    return {"size": size, "cells": out, "tiers": tiers}


def detail(layer, pk):
    """Level three: a short card (title, up to five facts, link) for one record, or None."""
    if layer == "farmers":
        farmer = Farmer.objects.filter(pk=pk, is_active=True).first()
        if not farmer:
            return None
        parcels = farmer.parcels.filter(is_active=True)
        area = float(sum(parcel.area_hectares for parcel in parcels))
        return {"title": farmer.full_name, "url": reverse("farmers:detail", args=[pk]), "rows": [
            ["Farmer no.", farmer.record_id], ["Barangay", farmer.barangay],
            ["Livelihood", farmer.get_livelihood_display()],
            ["Registration", farmer.get_registration_status_display()],
            ["Parcels", f"{parcels.count()} ({area:g} ha)"]]}
    if layer == "parcels":
        parcel = FarmParcel.objects.select_related("farmer").filter(pk=pk, is_active=True).first()
        if not parcel:
            return None
        crops = sorted({crop.crop_type for crop in parcel.crops.filter(is_active=True)})
        return {"title": parcel.display_name, "url": reverse("farm_parcels:detail", args=[pk]), "rows": [
            ["Farmer", f"{parcel.farmer.record_id} {parcel.farmer.full_name}"], ["Barangay", parcel.barangay],
            ["Area", f"{float(parcel.area_hectares):g} ha"], ["Ownership", parcel.get_ownership_type_display()],
            ["Commodities", ", ".join(crops[:3]) + (f" +{len(crops) - 3}" if len(crops) > 3 else "") or "None recorded"]]}
    if layer == "commodities":
        crop = CropRecord.objects.select_related("parcel__farmer").filter(pk=pk, is_active=True).first()
        if not crop:
            return None
        return {"title": crop.crop_type, "url": reverse("crops:detail", args=[pk]), "rows": [
            ["Farmer", f"{crop.parcel.farmer.record_id} {crop.parcel.farmer.full_name}"], ["Parcel", crop.parcel.display_name],
            ["Barangay", crop.parcel.barangay],
            ["Area", f"{float(crop.area_hectares):g} ha" if crop.area_hectares else "Not recorded"],
            ["Organic", "Yes" if crop.is_organic else "No"]]}
    if layer == "interventions":
        item = InterventionRecipient.objects.select_related("farmer", "intervention").filter(pk=pk).first()
        if not item:
            return None
        return {"title": item.intervention.get_intervention_type_display(),
                "url": reverse("interventions:detail", args=[item.intervention_id]), "rows": [
            ["Farmer", f"{item.farmer.record_id} {item.farmer.full_name}"], ["Barangay", item.farmer.barangay],
            ["Status", item.get_status_display()], ["Date", item.intervention.intervention_date.strftime("%b %d, %Y")],
            ["Details", item.intervention.description[:60]]]}
    item = ServiceRequest.objects.select_related("farmer", "service").filter(pk=pk, scope="INDIVIDUAL").first()
    if not item:
        return None
    return {"title": item.service.name, "url": reverse("service_requests:detail", args=[pk]), "rows": [
        ["Farmer", f"{item.farmer.record_id} {item.farmer.full_name}"], ["Barangay", item.farmer.barangay],
        ["Status", item.get_status_display()], ["Priority", item.get_priority_display()],
        ["Received", item.created_at.strftime("%b %d, %Y")]]}
