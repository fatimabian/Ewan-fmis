import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.farm_parcels.demo_locations import ROSARIO_BARANGAY_CENTERS
from apps.farm_parcels.models import FarmParcel
from apps.farm_parcels.views import is_within_rosario


COORDINATE_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def parse_coordinate(value):
    numbers = COORDINATE_PATTERN.findall(value or "")
    if len(numbers) < 2:
        return None
    latitude, longitude = float(numbers[0]), float(numbers[1])
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def coordinate_key(point):
    return round(point[0], 7), round(point[1], 7)


def likely_reference_point(point):
    """Return the reference name only for an almost exact centre-coordinate match."""
    for barangay, centre in ROSARIO_BARANGAY_CENTERS.items():
        latitude_metres = abs(point[0] - centre[0]) * 111_320
        longitude_metres = (
            abs(point[1] - centre[1])
            * 111_320
            * math.cos(math.radians(point[0]))
        )
        if math.hypot(latitude_metres, longitude_metres) <= 3:
            return barangay
    return ""


def build_coordinate_audit(barangay=""):
    parcels = FarmParcel.objects.filter(is_active=True)
    if barangay:
        parcels = parcels.filter(barangay=barangay)
    rows = list(
        parcels
        .values("pk", "barangay", "coordinates", "remarks")
        .order_by("pk")
    )
    coordinate_counts = Counter()
    parsed_rows = []
    missing = invalid = zero = outside = synthetic_saved = 0

    for row in rows:
        raw = (row["coordinates"] or "").strip()
        if not raw:
            missing += 1
            continue
        point = parse_coordinate(raw)
        if point is None:
            invalid += 1
            continue
        if point == (0.0, 0.0):
            zero += 1
        if not is_within_rosario(*point):
            outside += 1
        key = coordinate_key(point)
        coordinate_counts[key] += 1
        if (row["remarks"] or "").startswith("FMIS-DEMO-DATA:"):
            synthetic_saved += 1
        parsed_rows.append((row, point, key))

    duplicate_pairs = {
        point: count for point, count in coordinate_counts.items() if count > 1
    }
    flagged = []
    for row, point, key in parsed_rows:
        reasons = []
        if point == (0.0, 0.0):
            reasons.append("zero coordinate")
        if not is_within_rosario(*point):
            reasons.append("outside Rosario reference boundary")
        if key in duplicate_pairs:
            reasons.append(f"shared by {duplicate_pairs[key]} parcels")
        reference = likely_reference_point(point)
        if reference:
            reasons.append(f"matches {reference} reference centre")
        if (row["remarks"] or "").startswith("FMIS-DEMO-DATA:"):
            reasons.append("synthetic demo location; not field-verified")
        if reasons:
            flagged.append(
                {
                    "parcel": f"P-{row['pk']:04d}",
                    "barangay": row["barangay"],
                    "latitude": point[0],
                    "longitude": point[1],
                    "reasons": reasons,
                }
            )

    return {
        "summary": {
            "total_active_parcels": len(rows),
            "saved_coordinates": len(parsed_rows),
            "missing_coordinates": missing,
            "invalid_coordinates": invalid,
            "zero_coordinates": zero,
            "duplicate_coordinate_pairs": len(duplicate_pairs),
            "parcels_on_duplicate_coordinates": sum(duplicate_pairs.values()),
            "outside_rosario_reference_boundary": outside,
            "synthetic_saved_coordinates": synthetic_saved,
            "records_requiring_manual_verification": len(flagged),
        },
        "flagged_records": flagged,
        "notice": (
            "This is a read-only diagnostic. Flags are review indicators only; "
            "no parcel coordinate or barangay assignment was changed."
        ),
    }


class Command(BaseCommand):
    help = "Audit farm parcel coordinates without changing production records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            help="Optional JSON output file. Existing files are not overwritten.",
        )
        parser.add_argument(
            "--barangay",
            default="",
            help="Optionally audit one barangay using an exact database match.",
        )
        parser.add_argument(
            "--summary-only",
            action="store_true",
            help="Print aggregate counts without the flagged parcel list.",
        )

    def handle(self, *args, **options):
        report = build_coordinate_audit(options.get("barangay", "").strip())
        if options.get("summary_only"):
            report.pop("flagged_records", None)
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        output = options.get("output")
        if output:
            path = Path(output).expanduser().resolve()
            if path.exists():
                raise CommandError(f"Refusing to overwrite existing file: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"Coordinate audit written to {path}"))
            return
        self.stdout.write(rendered)
