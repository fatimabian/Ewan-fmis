import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.common.constants import (
    ROSARIO_BARANGAY_PSGC,
    ROSARIO_PSGC_CODE,
)
from apps.farm_parcels.models import RosarioBarangayBoundary


def property_value(properties, *names):
    normalized = {str(key).casefold(): value for key, value in (properties or {}).items()}
    for name in names:
        value = normalized.get(name.casefold())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def validate_feature_collection(payload):
    if payload.get("type") != "FeatureCollection":
        raise CommandError("Expected a GeoJSON FeatureCollection.")
    expected_by_code = {code: name for name, code in ROSARIO_BARANGAY_PSGC.items()}
    validated = []
    seen = set()
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        code = property_value(properties, "psgc_code", "psgc", "bgy_psgc", "code")
        name = property_value(properties, "barangay_name", "barangay", "name", "brgy_name")
        if code not in expected_by_code:
            continue
        expected_name = expected_by_code[code]
        if name.casefold() != expected_name.casefold():
            raise CommandError(f"PSGC {code} is named {name!r}; expected {expected_name!r}.")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise CommandError(f"{name} must use Polygon or MultiPolygon geometry.")
        if not geometry.get("coordinates"):
            raise CommandError(f"{name} has empty geometry.")
        if code in seen:
            raise CommandError(f"Duplicate PSGC feature: {code}.")
        seen.add(code)
        validated.append((code, expected_name, geometry))
    missing = sorted(set(expected_by_code) - seen)
    if missing:
        raise CommandError(
            "The dataset is incomplete for Rosario, Batangas. Missing PSGC codes: "
            + ", ".join(missing)
        )
    return validated


class Command(BaseCommand):
    help = "Validate and import an authoritative Rosario barangay GeoJSON dataset."

    def add_arguments(self, parser):
        parser.add_argument("geojson", help="Local GeoJSON downloaded through an authorized channel.")
        parser.add_argument("--source-agency", required=True, help="For example: NAMRIA / Geoportal Philippines")
        parser.add_argument("--source-url", required=True)
        parser.add_argument("--dataset-version", required=True)
        parser.add_argument("--expected-sha256", required=True)
        parser.add_argument("--dry-run", action="store_true", help="Validate without writing to the database.")

    def handle(self, *args, **options):
        path = Path(options["geojson"]).expanduser().resolve()
        if not path.is_file():
            raise CommandError(f"GeoJSON file not found: {path}")
        raw = path.read_bytes()
        actual_hash = hashlib.sha256(raw).hexdigest()
        if actual_hash.casefold() != options["expected_sha256"].casefold():
            raise CommandError("GeoJSON SHA-256 does not match the approved source checksum.")
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CommandError("The boundary file is not valid UTF-8 GeoJSON.") from error
        features = validate_feature_collection(payload)
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Validated {len(features)} PSGC-matched barangay polygons; no database changes made."))
            return
        with transaction.atomic():
            for code, name, geometry in features:
                RosarioBarangayBoundary.objects.update_or_create(
                    psgc_code=code,
                    defaults={
                        "barangay_name": name,
                        "municipality_psgc": ROSARIO_PSGC_CODE,
                        "geometry": geometry,
                        "source_agency": options["source_agency"],
                        "source_url": options["source_url"],
                        "dataset_version": options["dataset_version"],
                        "source_sha256": actual_hash,
                        "is_active": True,
                    },
                )
        self.stdout.write(self.style.SUCCESS(f"Imported {len(features)} authoritative Rosario barangay boundaries."))
