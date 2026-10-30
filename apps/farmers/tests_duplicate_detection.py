from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .duplicate_detection import (
    MAX_DATABASE_CANDIDATES,
    build_review_token,
    find_possible_duplicates,
    normalize_text,
    read_review_token,
)
from .models import Farmer


class FarmerDuplicateDetectionTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="duplicate.reviewer",
            password="ValidPass123!",
            role="STAFF",
            is_active=True,
        )
        self.existing = Farmer.objects.create(
            first_name="Maria",
            middle_name="Reyes",
            last_name="Dela Cruz",
            extension_name="Jr.",
            birth_date=date(1985, 4, 12),
            barangay="Alupay",
            valid_id_type="National ID",
            valid_id_number="1111222233334444",
        )

    def values(self, **overrides):
        values = {
            "first_name": "Marya",
            "middle_name": "Reyes",
            "last_name": "Dela Cruz",
            "extension_name": "Junior",
            "birth_date": "1985-04-12",
            "barangay": "Alupay",
            "valid_id_type": "Driver's License",
            "valid_id_number": "N01-23-456789",
        }
        values.update(overrides)
        return values

    def test_normalization_handles_case_spacing_accents_and_formatting(self):
        self.assertEqual(normalize_text("  MARÍA---Dela   Cruz "), "maria dela cruz")

    def test_minor_spelling_and_suffix_variation_are_flagged_with_reasons(self):
        matches = find_possible_duplicates(self.values())
        self.assertEqual(matches[0]["farmer"], self.existing)
        self.assertGreaterEqual(matches[0]["score"], 76)
        self.assertIn("Same birthdate", matches[0]["reasons"])

    def test_similar_name_with_different_identity_is_not_automatically_rejected(self):
        matches = find_possible_duplicates(
            self.values(
                first_name="Mario",
                birth_date="1998-01-01",
                barangay="Bagong Pook",
            )
        )
        self.assertIsInstance(matches, list)
        # A result is only a review flag; this service never deletes, merges, or saves.
        self.assertEqual(Farmer.objects.count(), 1)

    def test_review_token_is_bound_to_identity_candidates_and_reason(self):
        values = self.values()
        matches = find_possible_duplicates(values)
        token = build_review_token(values, matches, "Different household member")
        self.assertIsNotNone(read_review_token(token, values, matches))
        self.assertIsNone(
            read_review_token(token, {**values, "birth_date": "1990-01-01"}, matches)
        )

    def test_endpoint_returns_only_compact_non_sensitive_review_data(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("farmers:duplicate_check"), self.values())
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("no ML model is active", payload["method"])
        self.assertEqual(payload["matches"][0]["farmer_id"], self.existing.record_id)
        self.assertNotContains(response, self.existing.valid_id_number)

    def test_candidate_search_remains_one_bounded_database_query(self):
        Farmer.objects.bulk_create(
            [
                Farmer(
                    first_name=f"Person{index}",
                    last_name=f"Sample{index}",
                    barangay="Alupay" if index % 2 else "Bagong Pook",
                )
                for index in range(1000)
            ]
        )
        with CaptureQueriesContext(connection) as queries:
            matches = find_possible_duplicates(self.values())
        self.assertEqual(len(queries), 1)
        self.assertLessEqual(len(matches), 5)
        self.assertIn(f"LIMIT {MAX_DATABASE_CANDIDATES}", queries.captured_queries[0]["sql"])
