from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.farmers.models import Farmer
from apps.reports.analytics import descriptive_analytics


class DescriptiveAnalyticsTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="analytics-staff",
            password="StrongPass123!",
            role="STAFF",
        )
        Farmer.objects.create(
            first_name="Ana",
            last_name="Santos",
            barangay="Bagong Pook",
            sex="FEMALE",
            is_active=True,
        )

    def test_reports_and_analytics_require_authentication(self):
        response = self.client.get(reverse("reports:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("authentication:login"), response.url)

    def test_overview_uses_database_values_and_shows_all_tabs(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"),
            {"analytics_tab": "overview", "analytics_date_range": "all"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["descriptive"]["summary"][0]["value"], 1)
        self.assertContains(response, "Farmer Registrations Over Time")
        self.assertContains(response, "Generate Reports")
        self.assertNotContains(response, "phone_number")

    def test_barangay_filter_limits_analytics(self):
        matching = descriptive_analytics(
            "overview", "all", {"barangay": "Bagong Pook"}
        )
        empty = descriptive_analytics("overview", "all", {"barangay": "Alupay"})
        self.assertEqual(matching["summary"][0]["value"], 1)
        self.assertEqual(empty["summary"][0]["value"], 0)

    def test_generate_reports_tab_preserves_report_builder(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"), {"analytics_tab": "reports"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report Filters")
        self.assertContains(response, 'name="report_type"')
        self.assertContains(response, 'name="date_range"')
        self.assertContains(response, 'name="barangay"')
        self.assertContains(response, 'name="commodity"')
        self.assertContains(response, 'name="format"')
        self.assertContains(response, "Download Report")

    def test_every_descriptive_tab_renders(self):
        self.client.force_login(self.staff)
        for tab in ("overview", "farmers", "parcels", "commodities", "requests", "interventions"):
            with self.subTest(tab=tab):
                response = self.client.get(
                    reverse("reports:home"),
                    {"analytics_tab": tab, "analytics_date_range": "all"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["analytics_tab"], tab)

    def test_unknown_role_cannot_access_confidential_analytics(self):
        self.staff.role = "UNAUTHORIZED"
        self.staff.save(update_fields=["role"])
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))

    def test_overview_queries_remain_bounded_with_five_thousand_records(self):
        Farmer.objects.bulk_create(
            [
                Farmer(
                    first_name=f"Farmer {index}",
                    last_name="Performance",
                    barangay="Bagong Pook",
                    is_active=True,
                )
                for index in range(5000)
            ],
            batch_size=500,
        )
        with CaptureQueriesContext(connection) as queries:
            result = descriptive_analytics("overview", "all", {})
        self.assertEqual(result["summary"][0]["value"], 5001)
        self.assertLessEqual(len(queries), 35)
