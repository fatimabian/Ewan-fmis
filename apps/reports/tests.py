from django.contrib.auth import get_user_model
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from unittest.mock import patch

from apps.farmers.models import Farmer
from apps.inventory.models import InventoryItem, InventoryMovement
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
            birth_date=date(1950, 5, 10),
            is_four_ps=True,
            is_pwd=True,
            is_indigenous=True,
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

    def test_reports_navigation_lands_on_overview_for_staff_and_admin(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["analytics_tab"], "overview")
        self.assertContains(response, "Farmer Registrations Over Time")
        self.assertNotContains(response, "Report Filters")

        administrator = get_user_model().objects.create_user(
            username="analytics-admin",
            password="StrongPass123!",
            role="ADMIN",
            is_active=True,
        )
        self.client.force_login(administrator)
        response = self.client.get(reverse("reports:home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["analytics_tab"], "overview")
        self.assertContains(response, "Farmer Registrations Over Time")
        self.assertNotContains(response, "Governance Reports")

    def test_admin_generate_reports_tab_keeps_governance_reports(self):
        administrator = get_user_model().objects.create_user(
            username="reports-admin",
            password="StrongPass123!",
            role="ADMIN",
            is_active=True,
        )
        self.client.force_login(administrator)
        response = self.client.get(
            reverse("reports:home"), {"analytics_tab": "reports"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Governance Reports")
        self.assertNotContains(response, "Farmer Registrations Over Time")

    def test_barangay_filter_limits_analytics(self):
        matching = descriptive_analytics(
            "overview", "all", {"barangay": "Bagong Pook"}
        )
        empty = descriptive_analytics("overview", "all", {"barangay": "Alupay"})
        self.assertEqual(matching["summary"][0]["value"], 1)
        self.assertEqual(empty["summary"][0]["value"], 0)

    def test_farmer_statistics_are_live_filtered_database_counts(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"),
            {"analytics_tab": "farmers", "analytics_date_range": "all"},
        )

        self.assertEqual(response.status_code, 200)
        values = {
            item["label"]: item["value"]
            for item in response.context["descriptive"]["farmer_demographics"]
        }
        self.assertEqual(values["Female Farmers"], 1)
        self.assertEqual(values["Male Farmers"], 0)
        self.assertEqual(values["Senior Farmers"], 1)
        self.assertEqual(values["4Ps Beneficiaries"], 1)
        self.assertEqual(values["PWD Farmers"], 1)
        self.assertEqual(values["Indigenous Farmers"], 1)
        self.assertContains(response, "Farmer Statistics")
        self.assertContains(response, '<span class="analytics-kpi-icon"', count=7)

    def test_generate_reports_tab_preserves_report_builder(self):
        self.client.force_login(self.staff)
        with patch(
            "apps.reports.views.descriptive_analytics",
            side_effect=AssertionError("analytics must be lazy on the report generator"),
        ) as analytics_builder:
            response = self.client.get(
                reverse("reports:home"), {"analytics_tab": "reports"}
            )
        self.assertEqual(response.status_code, 200)
        analytics_builder.assert_not_called()
        self.assertContains(response, "Report Filters")
        self.assertContains(response, 'name="report_type"')
        self.assertContains(response, 'name="date_range"')
        self.assertContains(response, 'name="barangay"')
        self.assertContains(response, 'name="commodity"')
        self.assertContains(response, 'name="format"')
        self.assertContains(response, "Download Report")

    def test_generated_report_preview_analytics_use_the_filtered_report_rows(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"),
            {
                "analytics_tab": "reports",
                "report_type": "farmer_master",
                "date_range": "all",
                "view": "1",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report_preview"]["total_rows"], 1)
        self.assertEqual(
            response.context["report_preview"]["analytics_summary"][0]["value"],
            "1",
        )
        self.assertContains(response, "Filtered Report Analytics")
        self.assertContains(response, "Matching farmers")

    def test_every_descriptive_tab_renders(self):
        self.client.force_login(self.staff)
        for tab in (
            "overview",
            "farmers",
            "parcels",
            "commodities",
            "requests",
            "interventions",
            "inventory",
        ):
            with self.subTest(tab=tab):
                response = self.client.get(
                    reverse("reports:home"),
                    {"analytics_tab": tab, "analytics_date_range": "all"},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["analytics_tab"], tab)

    def test_analytics_filters_use_module_specific_popover_fields(self):
        self.client.force_login(self.staff)
        request_response = self.client.get(
            reverse("reports:home"), {"analytics_tab": "requests"}
        )
        self.assertContains(request_response, "Filter Service Requests")
        self.assertContains(request_response, 'data-filter-popover')
        self.assertContains(request_response, 'name="analytics_request_status"')
        self.assertContains(request_response, 'name="analytics_request_priority"')
        self.assertNotContains(request_response, 'name="analytics_inventory_category"')

        inventory_response = self.client.get(
            reverse("reports:home"), {"analytics_tab": "inventory"}
        )
        self.assertContains(inventory_response, "Filter Inventory")
        self.assertContains(inventory_response, 'name="analytics_inventory_category"')
        self.assertContains(
            inventory_response, 'name="analytics_inventory_movement_type"'
        )
        self.assertNotContains(inventory_response, 'name="analytics_barangay"')

    def test_inventory_analytics_describes_stock_and_movements(self):
        item = InventoryItem.objects.create(
            item_code="SEED-001",
            name="Certified Rice Seed",
            category="SEEDS",
            unit="bag",
            stock_on_hand=Decimal("8.00"),
            reorder_level=Decimal("10.00"),
            storage_location="Municipal Warehouse",
        )
        InventoryMovement.objects.create(
            item=item,
            movement_type=InventoryMovement.RECEIPT,
            quantity=Decimal("20.00"),
            balance_after=Decimal("20.00"),
            recorded_by=self.staff,
        )
        InventoryMovement.objects.create(
            item=item,
            movement_type=InventoryMovement.RELEASE,
            quantity=Decimal("12.00"),
            balance_after=Decimal("8.00"),
            recorded_by=self.staff,
        )

        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"),
            {"analytics_tab": "inventory", "analytics_date_range": "all"},
        )

        self.assertEqual(response.status_code, 200)
        descriptive = response.context["descriptive"]
        self.assertEqual(descriptive["inventory_item_total"], 1)
        self.assertEqual(descriptive["inventory_low_stock"], 1)
        self.assertEqual(descriptive["inventory_movement_total"], 2)
        self.assertEqual(descriptive["inventory_issued_items"][0]["value"], Decimal("12.00"))
        self.assertContains(response, "Inventory Movement Over Time")
        self.assertContains(response, "Current Stock Exceptions")
        self.assertContains(response, "Certified Rice Seed")

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
