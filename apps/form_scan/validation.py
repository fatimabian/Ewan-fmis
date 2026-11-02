"""Rule based checks on the values read from a form. Nothing here changes data."""
import re
from dataclasses import dataclass, field
from difflib import get_close_matches

from apps.common.constants import ROSARIO_BARANGAYS
from apps.common.geometry import haversine_m, polygon_area_ha
from apps.farm_parcels.demo_locations import ROSARIO_BARANGAY_CENTERS
from apps.farm_parcels.geojson import point_in_geojson
from apps.farm_parcels.models import FarmParcel, RosarioBarangayBoundary
from apps.ocr.conf import ocr_setting

from .coordinates import interpret

OK, WARN, FAIL = "ok", "warn", "fail"
GREEN, YELLOW, RED = "GREEN", "YELLOW", "RED"
OVERLAP_METERS = 10
NEAR_METERS = 50
AREA_TOLERANCE = 0.25
MAX_PLAUSIBLE_HECTARES = 500
APPROXIMATE_BARANGAY_KM = 3.5


@dataclass
class Check:
    code: str
    level: str
    title: str
    message: str
    # Field values to offer as a one click fix, e.g. {"latitude": "13.84", "longitude": "121.29"}.
    suggestion: dict = field(default_factory=dict)

    def as_dict(self):
        return {"code": self.code, "level": self.level, "title": self.title,
                "message": self.message, "suggestion": self.suggestion}


@dataclass
class ValidationResult:
    status: str
    checks: list
    point: tuple | None
    suggested_point: tuple | None

    @property
    def blocks_approval(self):
        return self.status == RED


def normalize_barangay(text):
    """Return (canonical name or None, close match or None) for a written barangay."""
    cleaned = re.sub(r"^(?:brgy\.?|barangay\s+(?=\D{3,}))\s*", "", (text or "").strip(), flags=re.I)
    lookup = {name.casefold(): name for name in ROSARIO_BARANGAYS}
    if cleaned.casefold() in lookup:
        return lookup[cleaned.casefold()], None
    close = get_close_matches(cleaned.casefold(), list(lookup), n=1, cutoff=0.85)
    return None, (lookup[close[0]] if close else None)


def parse_area_hectares(text):
    """Return (hectares or None, converted_from_text or None)."""
    match = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*([a-zA-Z²2. ]*)$", text or "")
    if not match:
        return None, None
    number = float(match[1].replace(",", "."))
    unit = match[2].strip().lower().replace(".", "").replace(" ", "")
    if unit in {"sqm", "m2", "m²", "sqmeters", "sqmetres", "squaremeters", "squaremetres"}:
        return number / 10_000, f"{match[1]} sq m"
    if unit in {"", "ha", "has", "hectare", "hectares"}:
        return number, None
    return None, None


def _barangay_polygons():
    return {
        row.barangay_name: row.geometry
        for row in RosarioBarangayBoundary.objects.filter(is_active=True)
    }


def _containing_barangay(point, polygons):
    return next((name for name, geometry in polygons.items() if point_in_geojson(*point, geometry)), None)


def _check_coordinates(values):
    """Format, boundary and typo checks. Returns (checks, point_to_use, suggested_point)."""
    latitude, longitude = values.get("latitude", "").strip(), values.get("longitude", "").strip()
    if not latitude and not longitude:
        return [Check("coordinates", WARN, "Location", "No coordinates were written. The parcel will be saved without a map pin.")], None, None
    reading = interpret(latitude, longitude)
    if reading.unreadable:
        return [Check("coordinates", FAIL, "Location", "The coordinates could not be read as numbers. Type them as decimal degrees, for example 13.7967 and 121.2351.")], None, None
    if reading.in_rosario and "dms" in reading.fixes:
        lat, lng = reading.suggestion
        return [Check("coordinates", WARN, "Location", f"Written in degrees, minutes, seconds. Decimal equivalent: {lat:.6f}, {lng:.6f}.", {"latitude": f"{lat:.6f}", "longitude": f"{lng:.6f}"})], reading.as_read, reading.suggestion
    if reading.in_rosario:
        return [Check("coordinates", OK, "Location", "Inside the Rosario boundary.")], reading.as_read, None
    if reading.suggestion:
        lat, lng = reading.suggestion
        return [Check("coordinates", FAIL, "Location", f"Outside Rosario as written; {reading.explanation}. Suggested: {lat:.6f}, {lng:.6f}. Review the form image before accepting.", {"latitude": f"{lat:.6f}", "longitude": f"{lng:.6f}"})], None, reading.suggestion
    return [Check("coordinates", FAIL, "Location", "These coordinates are outside Rosario and no simple typo explains it. Check the form or leave them blank.")], None, None


def _check_barangay(values, point):
    written = values.get("barangay", "").strip()
    barangay, close = normalize_barangay(written)
    checks = []
    if not written:
        checks.append(Check("barangay", WARN, "Barangay", "No barangay was written."))
    elif barangay is None:
        suggestion = {"barangay": close} if close else {}
        hint = f" Did you mean {close}?" if close else ""
        checks.append(Check("barangay", WARN, "Barangay", f"'{written}' is not a Rosario barangay.{hint}", suggestion))
    else:
        checks.append(Check("barangay", OK, "Barangay", f"{barangay} is a Rosario barangay."))
    if point and barangay:
        checks.append(_barangay_match(barangay, point))
    return checks


def _barangay_match(barangay, point):
    """Is the point inside the barangay written on the form?"""
    polygons = _barangay_polygons()
    if polygons:
        actual = _containing_barangay(point, polygons)
        if actual == barangay:
            return Check("barangay_match", OK, "Pin and barangay", f"The pin is inside {barangay}.")
        where = f"inside {actual}" if actual else "outside every barangay boundary"
        suggestion = {"barangay": actual} if actual else {}
        return Check("barangay_match", FAIL, "Pin and barangay", f"The form says {barangay} but the pin is {where}.", suggestion)
    # Boundaries were not imported: compare with the published reference points instead.
    centre = ROSARIO_BARANGAY_CENTERS.get(barangay)
    nearest = min(ROSARIO_BARANGAY_CENTERS, key=lambda name: haversine_m(point, ROSARIO_BARANGAY_CENTERS[name]))
    if centre and nearest != barangay and haversine_m(point, centre) / 1000 > APPROXIMATE_BARANGAY_KM:
        return Check("barangay_match", WARN, "Pin and barangay", f"The pin is far from {barangay} and closest to {nearest}. Barangay boundaries are not imported, so this check is approximate.", {"barangay": nearest})
    return Check("barangay_match", OK, "Pin and barangay", f"The pin is near {barangay}. Barangay boundaries are not imported, so this check is approximate.")


def _check_overlap(point, exclude_parcel_pk):
    """Overlap or near duplicate with an existing parcel pin."""
    from apps.farm_parcels.coordinate_services import parse_coordinates

    rows = (
        FarmParcel.objects.filter(is_active=True, farmer__is_active=True)
        .exclude(coordinates="")
        .exclude(pk=exclude_parcel_pk)
        .values_list("pk", "coordinates", "farmer__last_name", "farmer__first_name")
    )
    nearest = None
    for pk, text, last_name, first_name in rows.iterator(chunk_size=1000):
        other = parse_coordinates(text)
        if not other:
            continue
        distance = haversine_m(point, other)
        if distance <= NEAR_METERS and (nearest is None or distance < nearest[0]):
            nearest = (distance, pk, f"{first_name} {last_name}")
    if nearest is None:
        return Check("overlap", OK, "Existing parcels", "No existing parcel pin is within 50 m.")
    distance, pk, owner = nearest
    label = f"P-{pk:04d} ({owner}), {distance:.0f} m away"
    if distance <= OVERLAP_METERS:
        return Check("overlap", FAIL, "Existing parcels", f"This pin overlaps {label}. It is probably a duplicate.")
    return Check("overlap", WARN, "Existing parcels", f"Close to {label}. Confirm this is a different parcel.")


def _check_area(values, polygon):
    text = values.get("area_hectares", "").strip()
    if not text:
        return Check("area", WARN, "Farm area", "No farm area was written.")
    hectares, converted = parse_area_hectares(text)
    if hectares is None or hectares <= 0:
        return Check("area", WARN, "Farm area", f"'{text}' could not be read as hectares.")
    if hectares > MAX_PLAUSIBLE_HECTARES:
        return Check("area", WARN, "Farm area", f"{hectares:g} ha is unusually large for one parcel.")
    if converted:
        return Check("area", WARN, "Farm area", f"{converted} is {hectares:g} ha.", {"area_hectares": f"{hectares:g}"})
    if polygon:
        drawn = polygon_area_ha([tuple(vertex) for vertex in polygon])
        if drawn and abs(drawn - hectares) / hectares > AREA_TOLERANCE:
            return Check("area", WARN, "Farm area", f"The form says {hectares:g} ha but the drawn polygon is {drawn:.2f} ha.", {"area_hectares": f"{drawn:.2f}"})
    return Check("area", OK, "Farm area", f"{hectares:g} ha.")


def _check_confidence(values, confidences, threshold):
    low = sorted(name for name, score in (confidences or {}).items() if values.get(name, "").strip() and score is not None and score < threshold)
    if low:
        names = ", ".join(name.replace("_", " ") for name in low)
        return Check("confidence", WARN, "Handwriting", f"The reader was unsure about: {names}. Compare with the form image.")
    return Check("confidence", OK, "Handwriting", "The reader was confident about every field.")


def validate(values, confidences=None, *, polygon=None, exclude_parcel_pk=None, threshold=None):
    """Run every rule and return the traffic light with the individual checks."""
    threshold = ocr_setting("CONFIDENCE_THRESHOLD") if threshold is None else threshold
    checks, point, suggested = _check_coordinates(values)
    checks += _check_barangay(values, point)
    if point:
        checks.append(_check_overlap(point, exclude_parcel_pk))
    checks.append(_check_area(values, polygon))
    checks.append(_check_confidence(values, confidences, threshold))
    levels = {check.level for check in checks}
    status = RED if FAIL in levels else YELLOW if WARN in levels else GREEN
    return ValidationResult(status, checks, point, suggested)
