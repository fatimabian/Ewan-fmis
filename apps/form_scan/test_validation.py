from django.test import SimpleTestCase, TestCase, override_settings

from apps.farm_parcels.models import FarmParcel, RosarioBarangayBoundary
from apps.farmers.models import Farmer

from .coordinates import interpret
from .validation import FAIL, GREEN, OK, RED, WARN, YELLOW, normalize_barangay, parse_area_hectares, validate

# A clean Bulihan form: a point inside Rosario, written correctly.
GOOD = {
    "farmer_name": "Dela Cruz, Juan", "barangay": "Bulihan", "latitude": "13.7967",
    "longitude": "121.2351", "area_hectares": "1.5", "parcel_name": "", "commodity": "Rice",
}
CONFIDENT = {"farmer_name": 0.95, "barangay": 0.95, "latitude": 0.95, "longitude": 0.95, "area_hectares": 0.95}


def check(result, code):
    return next(item for item in result.checks if item.code == code)


class CoordinateInterpretationTests(SimpleTestCase):
    def test_correct_decimal_degrees(self):
        reading = interpret("13.7967", "121.2351")
        self.assertTrue(reading.in_rosario)
        self.assertIsNone(reading.suggestion)

    def test_swapped_latitude_and_longitude(self):
        reading = interpret("121.2036", "13.8382")
        self.assertFalse(reading.in_rosario)
        self.assertEqual(reading.fixes, ("swap",))
        self.assertEqual(reading.suggestion, (13.8382, 121.2036))

    def test_missing_decimal_points(self):
        reading = interpret("138404", "1212922")
        self.assertEqual(reading.fixes, ("decimal",))
        self.assertEqual(reading.suggestion, (13.8404, 121.2922))

    def test_dropped_leading_digit(self):
        self.assertEqual(interpret("3.8404", "121.2922").suggestion, (13.8404, 121.2922))
        self.assertEqual(interpret("13.8404", "21.2922").suggestion, (13.8404, 121.2922))
        self.assertEqual(interpret("13.8404", "21.2922").fixes, ("digit",))

    def test_wrong_sign(self):
        reading = interpret("13.8404", "-121.2922")
        self.assertEqual(reading.fixes, ("sign",))
        self.assertEqual(reading.suggestion, (13.8404, 121.2922))

    def test_degrees_minutes_seconds_is_converted_but_flagged(self):
        reading = interpret("13°48'26.6\"N", "121°18'54.7\"E")
        self.assertTrue(reading.in_rosario)
        self.assertEqual(reading.fixes, ("dms",))
        self.assertAlmostEqual(reading.suggestion[0], 13.807389, places=5)
        self.assertAlmostEqual(reading.suggestion[1], 121.315194, places=5)

    def test_combined_swap_and_missing_decimal(self):
        reading = interpret("1212922", "138404")
        self.assertEqual(set(reading.fixes), {"swap", "decimal"})
        self.assertEqual(reading.suggestion, (13.8404, 121.2922))

    def test_valid_point_outside_rosario_gets_no_suggestion(self):
        reading = interpret("14.5995", "120.9842")
        self.assertFalse(reading.in_rosario)
        self.assertIsNone(reading.suggestion)

    def test_unreadable_text(self):
        self.assertTrue(interpret("abc", "12").unreadable)
        self.assertTrue(interpret("", "").unreadable)


class HelperTests(SimpleTestCase):
    def test_barangay_names(self):
        self.assertEqual(normalize_barangay("bulihan"), ("Bulihan", None))
        self.assertEqual(normalize_barangay("Brgy. Bulihan"), ("Bulihan", None))
        self.assertEqual(normalize_barangay("Barangay A"), ("Barangay A", None))
        self.assertEqual(normalize_barangay("Bulihan "), ("Bulihan", None))
        self.assertEqual(normalize_barangay("Bulihn"), (None, "Bulihan"))
        self.assertEqual(normalize_barangay("Atlantis"), (None, None))

    def test_area_units(self):
        self.assertEqual(parse_area_hectares("1.5"), (1.5, None))
        self.assertEqual(parse_area_hectares("2 ha"), (2.0, None))
        self.assertEqual(parse_area_hectares("5000 sqm")[0], 0.5)
        self.assertEqual(parse_area_hectares("lots"), (None, None))


class StatusTests(TestCase):
    def test_all_checks_pass_is_green(self):
        result = validate(GOOD, CONFIDENT)
        self.assertEqual(result.status, GREEN)
        self.assertFalse(result.blocks_approval)

    def test_low_confidence_is_yellow(self):
        result = validate(GOOD, {**CONFIDENT, "area_hectares": 0.4})
        self.assertEqual(result.status, YELLOW)
        self.assertEqual(check(result, "confidence").level, WARN)
        self.assertIn("area hectares", check(result, "confidence").message)

    def test_threshold_is_configurable(self):
        confidences = {**CONFIDENT, "area_hectares": 0.8}
        self.assertEqual(validate(GOOD, confidences, threshold=0.9).status, YELLOW)
        with override_settings(OCR={"CONFIDENCE_THRESHOLD": 0.5}):
            self.assertEqual(validate(GOOD, confidences).status, GREEN)

    def test_empty_value_never_counts_as_low_confidence(self):
        values = {**GOOD, "parcel_name": ""}
        self.assertEqual(validate(values, {**CONFIDENT, "parcel_name": 0.0}).status, GREEN)

    def test_outside_rosario_is_red_and_blocks(self):
        result = validate({**GOOD, "latitude": "14.5995", "longitude": "120.9842"}, CONFIDENT)
        self.assertEqual(result.status, RED)
        self.assertTrue(result.blocks_approval)
        self.assertEqual(check(result, "coordinates").level, FAIL)

    def test_typo_with_suggestion_is_red_and_offers_fix(self):
        result = validate({**GOOD, "latitude": "121.2351", "longitude": "13.7967"}, CONFIDENT)
        self.assertEqual(result.status, RED)
        fix = check(result, "coordinates").suggestion
        self.assertEqual(fix, {"latitude": "13.796700", "longitude": "121.235100"})
        self.assertEqual(result.suggested_point, (13.7967, 121.2351))
        self.assertIsNone(result.point)  # the wrong value is never used as the pin

    def test_applying_the_suggestion_clears_red(self):
        values = {**GOOD, "latitude": "121.2351", "longitude": "13.7967"}
        values.update(check(validate(values, CONFIDENT), "coordinates").suggestion)
        self.assertEqual(validate(values, CONFIDENT).status, GREEN)

    def test_dms_is_yellow_with_decimal_suggestion(self):
        values = {**GOOD, "barangay": "San Isidro", "latitude": "13°48'26.6\"N", "longitude": "121°18'54.7\"E"}
        result = validate(values, CONFIDENT)
        self.assertEqual(result.status, YELLOW)
        self.assertEqual(check(result, "coordinates").suggestion["latitude"], "13.807389")

    def test_missing_coordinates_is_yellow(self):
        result = validate({**GOOD, "latitude": "", "longitude": ""}, CONFIDENT)
        self.assertEqual(result.status, YELLOW)
        self.assertEqual(check(result, "coordinates").level, WARN)

    def test_unreadable_coordinates_is_red(self):
        self.assertEqual(validate({**GOOD, "latitude": "abc"}, CONFIDENT).status, RED)

    def test_unknown_barangay_is_yellow_with_suggestion(self):
        result = validate({**GOOD, "barangay": "Bulihn"}, CONFIDENT)
        self.assertEqual(result.status, YELLOW)
        self.assertEqual(check(result, "barangay").suggestion, {"barangay": "Bulihan"})

    def test_area_in_square_metres_is_yellow_with_conversion(self):
        result = validate({**GOOD, "area_hectares": "5000 sqm"}, CONFIDENT)
        self.assertEqual(result.status, YELLOW)
        self.assertEqual(check(result, "area").suggestion, {"area_hectares": "0.5"})

    def test_implausible_or_unreadable_area_is_yellow(self):
        self.assertEqual(validate({**GOOD, "area_hectares": "9000"}, CONFIDENT).status, YELLOW)
        self.assertEqual(validate({**GOOD, "area_hectares": "big"}, CONFIDENT).status, YELLOW)
        self.assertEqual(validate({**GOOD, "area_hectares": ""}, CONFIDENT).status, YELLOW)

    def test_without_ocr_confidences_only_the_rules_apply(self):
        self.assertEqual(validate(GOOD, None).status, GREEN)


class BarangayMatchTests(TestCase):
    def test_reference_point_fallback_is_approximate_and_yellow(self):
        # Alupay is in the north east; the Bulihan pin is far from it.
        result = validate({**GOOD, "barangay": "Alupay"}, CONFIDENT)
        match = check(result, "barangay_match")
        self.assertEqual(match.level, WARN)
        self.assertIn("approximate", match.message)

    def test_boundary_polygon_mismatch_is_red(self):
        def box(south, west, north, east):
            return {"type": "Polygon", "coordinates": [[[west, south], [east, south], [east, north], [west, north], [west, south]]]}

        for name, geometry in (("Bulihan", box(13.79, 121.23, 13.80, 121.24)), ("Alupay", box(13.83, 121.28, 13.85, 121.30))):
            RosarioBarangayBoundary.objects.create(
                psgc_code=name[:3] + "0", barangay_name=name, geometry=geometry,
                source_agency="test", source_url="https://example.test", dataset_version="t", source_sha256="0" * 64,
            )
        self.assertEqual(validate(GOOD, CONFIDENT).status, GREEN)
        mismatch = validate({**GOOD, "barangay": "Alupay"}, CONFIDENT)
        self.assertEqual(mismatch.status, RED)
        self.assertEqual(check(mismatch, "barangay_match").level, FAIL)
        self.assertEqual(check(mismatch, "barangay_match").suggestion, {"barangay": "Bulihan"})

    def test_pin_outside_every_boundary_is_red(self):
        RosarioBarangayBoundary.objects.create(
            psgc_code="X1", barangay_name="Alupay",
            geometry={"type": "Polygon", "coordinates": [[[121.28, 13.83], [121.30, 13.83], [121.30, 13.85], [121.28, 13.83]]]},
            source_agency="t", source_url="https://example.test", dataset_version="t", source_sha256="0" * 64,
        )
        self.assertEqual(validate({**GOOD, "barangay": "Alupay"}, CONFIDENT).status, RED)


class OverlapTests(TestCase):
    def setUp(self):
        self.farmer = Farmer.objects.create(first_name="Maria", last_name="Santos", barangay="Bulihan")
        self.parcel = FarmParcel.objects.create(
            farmer=self.farmer, barangay="Bulihan", area_hectares="1.00", ownership_type="OWNED",
            coordinates="13.7967000, 121.2351000",
        )

    def test_same_spot_is_red(self):
        result = validate(GOOD, CONFIDENT)
        self.assertEqual(result.status, RED)
        self.assertIn(f"P-{self.parcel.pk:04d}", check(result, "overlap").message)

    def test_a_few_metres_away_is_still_red(self):
        result = validate({**GOOD, "latitude": "13.79675"}, CONFIDENT)  # about 5.5 m
        self.assertEqual(check(result, "overlap").level, FAIL)

    def test_tens_of_metres_away_is_a_yellow_warning(self):
        result = validate({**GOOD, "latitude": "13.79700"}, CONFIDENT)  # about 37 m
        self.assertEqual(check(result, "overlap").level, WARN)
        self.assertEqual(result.status, YELLOW)

    def test_far_away_is_fine(self):
        self.assertEqual(check(validate({**GOOD, "latitude": "13.7990"}, CONFIDENT), "overlap").level, OK)

    def test_editing_the_same_parcel_is_not_an_overlap(self):
        result = validate(GOOD, CONFIDENT, exclude_parcel_pk=self.parcel.pk)
        self.assertEqual(check(result, "overlap").level, OK)

    def test_inactive_parcels_are_ignored(self):
        FarmParcel.objects.update(is_active=False)
        self.assertEqual(check(validate(GOOD, CONFIDENT), "overlap").level, OK)


class AreaAgainstPolygonTests(SimpleTestCase):
    # About 1 ha: 100 m by 100 m near 13.8 N.
    SQUARE_1HA = [(13.8, 121.2), (13.8, 121.20092), (13.80090, 121.20092), (13.80090, 121.2)]

    def test_matching_area_passes(self):
        result = validate_area("1.0", self.SQUARE_1HA)
        self.assertEqual(result.level, OK)

    def test_large_mismatch_warns_with_drawn_area(self):
        result = validate_area("3.0", self.SQUARE_1HA)
        self.assertEqual(result.level, WARN)
        self.assertIn("drawn polygon", result.message)
        self.assertIn("area_hectares", result.suggestion)


def validate_area(text, polygon):
    from .validation import _check_area

    return _check_area({"area_hectares": text}, polygon)
