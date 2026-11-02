"""What each GIS map layer shows. Layers return plain records; views shape them for the browser."""
from dataclasses import dataclass

from django.urls import reverse

from apps.common.constants import COMMODITY_DETAIL_TO_GROUP, commodity_group
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel, ParcelCoordinateReview
from apps.farm_parcels.views import FarmParcelMapView, parcel_pin_status
from apps.farmers.models import Farmer
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


@dataclass(frozen=True)
class Layer:
    key: str
    label: str
    icon: str
    legend: tuple  # at most three (status, label) pairs
    status_options: tuple  # (value, label)
    uses_commodity: bool


ATTENTION_OPTIONS = ((ALL, "Everything"), (ATTENTION_ONLY, "Needs attention only"))
LAYERS = {
    layer.key: layer
    for layer in (
        Layer("farmers", "Farmers", "bi-person-fill",
              ((GOOD, "Registration completed"), (ATTENTION, "Registration not completed")),
              ATTENTION_OPTIONS, True),
        Layer("parcels", "Farm parcels", "bi-pentagon-fill",
              ((GOOD, "Pin verified"), (ATTENTION, "Pin needs verification")),
              ATTENTION_OPTIONS, True),
        Layer("commodities", "Commodities", "bi-tree-fill",
              ((GOOD, "Pin verified"), (ATTENTION, "Pin needs verification")),
              ATTENTION_OPTIONS, True),
        Layer("requests", "Service requests", "bi-clipboard-check-fill",
              ((ATTENTION, "Pending"), (NEUTRAL, "In progress"), (GOOD, "Completed")),
              (("open", "Open requests"), ("PENDING", "Pending only"),
               ("IN_PROGRESS", "In progress only"), ("COMPLETED", "Completed")), False),
    )
}


def parse_point(text):
    return FarmParcelMapView.parse_coordinates(text) if (text or "").strip() else None


def _pin_statuses():
    """Parcel id -> good/attention, using the same rules as the farm parcel map."""
    pending = set(
        ParcelCoordinateReview.objects.filter(status=ParcelCoordinateReview.STATUS_PENDING)
        .values_list("parcel_id", flat=True)
    )
    return pending


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
        point = parse_point(text)
        if point:
            points[pk] = point
    parcels = (
        FarmParcel.objects.filter(is_active=True, farmer_id__in=farmer_ids).exclude(coordinates="")
        .order_by("pk").values_list("farmer_id", "coordinates")
    )
    for farmer_id, text in parcels:
        if farmer_id not in points and (point := parse_point(text)):
            points[farmer_id] = point
    return points


def _parcel_records(barangay, commodity):
    parcels = FarmParcel.objects.filter(is_active=True, farmer__is_active=True)
    if barangay:
        parcels = parcels.filter(barangay=barangay)
    if commodity:
        parcels = parcels.filter(pk__in=_commodity_parcel_ids(commodity))
    pending = _pin_statuses()
    return [
        Record(pk, bgy, parse_point(text), _status_of_pin(pk, text, remarks, pending))
        for pk, bgy, text, remarks in parcels.values_list("pk", "barangay", "coordinates", "remarks")
    ]


def _commodity_records(barangay, commodity):
    crops = CropRecord.objects.filter(is_active=True, parcel__is_active=True, parcel__farmer__is_active=True)
    if barangay:
        crops = crops.filter(parcel__barangay=barangay)
    pending = _pin_statuses()
    rows = crops.values_list("pk", "crop_type", "parcel_id", "parcel__barangay", "parcel__coordinates", "parcel__remarks")
    return [
        Record(pk, bgy, parse_point(text), _status_of_pin(parcel_id, text, remarks, pending))
        for pk, crop_type, parcel_id, bgy, text, remarks in rows
        if not commodity or commodity_group(crop_type) == commodity
    ]


def _farmers_for(barangay, commodity):
    farmers = Farmer.objects.filter(is_active=True)
    if barangay:
        farmers = farmers.filter(barangay=barangay)
    if commodity:
        owners = FarmParcel.objects.filter(pk__in=_commodity_parcel_ids(commodity)).values_list("farmer_id", flat=True)
        farmers = farmers.filter(pk__in=list(owners))
    return farmers


def _farmer_records(barangay, commodity):
    rows = list(_farmers_for(barangay, commodity).values_list("pk", "barangay", "registration_status"))
    points = _farmer_points([row[0] for row in rows])
    return [
        Record(pk, bgy, points.get(pk), GOOD if registration == "COMPLETED" else ATTENTION)
        for pk, bgy, registration in rows
    ]


REQUEST_STATUS = {"PENDING": ATTENTION, "IN_PROGRESS": NEUTRAL, "COMPLETED": GOOD}


def _request_records(barangay, commodity, status):
    requests = ServiceRequest.objects.filter(scope="INDIVIDUAL", farmer__is_active=True)
    requests = requests.filter(status__in=OPEN_REQUESTS if status in ("", "open") else [status])
    if barangay:
        requests = requests.filter(farmer__barangay=barangay)
    rows = list(requests.values_list("pk", "status", "farmer_id", "farmer__barangay"))
    points = _farmer_points({row[2] for row in rows})
    return [Record(pk, bgy, points.get(farmer_id), REQUEST_STATUS[state]) for pk, state, farmer_id, bgy in rows]


def records(layer, *, barangay="", commodity="", status=""):
    """All records of a layer matching the filters, mapped or not."""
    if layer == "parcels":
        found = _parcel_records(barangay, commodity)
    elif layer == "commodities":
        found = _commodity_records(barangay, commodity)
    elif layer == "farmers":
        found = _farmer_records(barangay, commodity)
    else:
        return _request_records(barangay, commodity, status)
    return [r for r in found if r.status == ATTENTION] if status == ATTENTION_ONLY else found


def detail(layer, pk):
    """Level three: a short card (title, up to five facts, link) for one record, or None."""
    if layer == "farmers":
        farmer = Farmer.objects.filter(pk=pk, is_active=True).first()
        if not farmer:
            return None
        parcels = farmer.parcels.filter(is_active=True)
        area = float(sum(parcel.area_hectares for parcel in parcels))
        return {"title": farmer.full_name, "url": reverse("farmers:detail", args=[pk]), "rows": [
            ["Barangay", farmer.barangay], ["Livelihood", farmer.get_livelihood_display()],
            ["Registration", farmer.get_registration_status_display()],
            ["Parcels", f"{parcels.count()} ({area:g} ha)"]]}
    if layer == "parcels":
        parcel = FarmParcel.objects.select_related("farmer").filter(pk=pk, is_active=True).first()
        if not parcel:
            return None
        crops = sorted({crop.crop_type for crop in parcel.crops.filter(is_active=True)})
        return {"title": parcel.display_name, "url": reverse("farm_parcels:detail", args=[pk]), "rows": [
            ["Farmer", parcel.farmer.full_name], ["Barangay", parcel.barangay],
            ["Area", f"{float(parcel.area_hectares):g} ha"], ["Ownership", parcel.get_ownership_type_display()],
            ["Commodities", ", ".join(crops[:3]) + (f" +{len(crops) - 3}" if len(crops) > 3 else "") or "None recorded"]]}
    if layer == "commodities":
        crop = CropRecord.objects.select_related("parcel__farmer").filter(pk=pk, is_active=True).first()
        if not crop:
            return None
        return {"title": crop.crop_type, "url": reverse("crops:detail", args=[pk]), "rows": [
            ["Farmer", crop.parcel.farmer.full_name], ["Parcel", crop.parcel.display_name],
            ["Barangay", crop.parcel.barangay],
            ["Area", f"{float(crop.area_hectares):g} ha" if crop.area_hectares else "Not recorded"],
            ["Variety", crop.variety or "Not recorded"]]}
    item = ServiceRequest.objects.select_related("farmer", "service").filter(pk=pk, scope="INDIVIDUAL").first()
    if not item:
        return None
    return {"title": item.service.name, "url": reverse("service_requests:detail", args=[pk]), "rows": [
        ["Farmer", item.farmer.full_name], ["Barangay", item.farmer.barangay],
        ["Status", item.get_status_display()], ["Priority", item.get_priority_display()],
        ["Received", item.created_at.strftime("%b %d, %Y")]]}
