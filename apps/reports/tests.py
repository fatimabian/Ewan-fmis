from django.contrib.auth import get_user_model
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from apps.farmers.models import Farmer
from apps.farmers.duplicate_detection import find_system_duplicate_pairs
from apps.inventory.models import InventoryItem, InventoryMovement
from apps.reports.analytics import _monthly_series, descriptive_analytics
from apps.reports.export import generate_table_export


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

    def test_overview_shows_summary_and_separate_registry_tabs(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"), {"analytics_tab": "overview"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["analytics_tab"], "overview")
        self.assertEqual(response.context["descriptive"]["summary"][0]["value"], 1)
        self.assertEqual([key for key, label in response.context["analytics_tabs"]],
                         ["overview", "farmers", "commodities", "parcels", "requests", "interventions", "inventory", "reports"])
        self.assertContains(response, "Leading Commodities")
        self.assertContains(response, "Service Requests Over Time")
        self.assertContains(response, "Top five barangays by matching active farmer records.")
        self.assertNotContains(response, "Farmer Statistics")
        self.assertNotContains(response, 'aria-label="Farmers by Barangay bar chart"')
        self.assertNotContains(response, 'name="report_type"')

    def test_duplicate_table_paginates_eight_pairs_and_preserves_filters(self):
        self.client.force_login(self.staff)
        farmer = Farmer.objects.first()
        pairs = [
            {"left_pk": farmer.pk, "right_pk": farmer.pk, "left_id": f"Pair-{index}",
             "right_id": "Match", "left_name": "First", "right_name": "Second",
             "score": 80, "reasons": ["Similar names"]}
            for index in range(17)
        ]
        def scan():
            return {"total": 17, "pairs": list(pairs), "records_scanned": 18, "method": "test"}
        with patch("apps.reports.analytics.find_system_duplicate_pairs", side_effect=scan):
            for number, count in ((1, 8), (2, 8), (3, 1)):
                response = self.client.get(reverse("reports:home"), {
                    "analytics_tab": "farmers", "duplicate_page": number,
                    "analytics_barangay": "Bagong Pook",
                })
                self.assertEqual(response.status_code, 200)
                duplicates = response.context["descriptive"]["duplicate_scan"]
                self.assertEqual(len(duplicates["pairs"]), count)
                self.assertEqual(duplicates["page_obj"].number, number)
                self.assertEqual(duplicates["total"], 17)
                self.assertContains(response, 'name="duplicate_page"')
                self.assertContains(response, 'name="analytics_barangay" value="Bagong Pook"')
                self.assertContains(response, 'analytics-duplicate-scroll')
                self.assertContains(response, f"Pair-{(number - 1) * 8}")
                if number == 1:
                    self.assertNotContains(response, "Pair-8 ·")
                    self.assertContains(response, "duplicate_page=2")

    def test_reports_navigation_uses_staff_overview_and_admin_governance_reports(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"))
        self.assertEqual(response.context["analytics_tab"], "overview")
        self.assertContains(response, 'aria-label="Reports and analytics sections"', count=1)
        administrator = get_user_model().objects.create_user(username="analytics-admin", role="ADMIN")
        self.client.force_login(administrator)
        response = self.client.get(reverse("reports:home"))
        self.assertEqual(response.context["analytics_tab"], "reports")
        self.assertContains(response, "Governance Reports")
        self.assertNotContains(response, 'aria-label="Reports and analytics sections"')

    def test_admin_generate_reports_tab_keeps_governance_reports(self):
        administrator = get_user_model().objects.create_user(username="reports-admin", role="ADMIN")
        self.client.force_login(administrator)
        response = self.client.get(reverse("reports:home"), {"analytics_tab": "reports"})
        self.assertEqual(response.status_code, 200)
        for title in ("Governance Reports", "System Overview", "User Account Registry", "Activity Audit Trail"):
            self.assertContains(response, title)
        self.assertNotContains(response, "Farmer Master List")
        self.assertNotContains(response, "Barangays with the Most Farmers")

    def test_downloaded_pdf_uses_the_shared_official_da_header(self):
        from pypdf import PdfReader

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("reports:home"),
            {"report_type": "farmer_master", "date_range": "all", "format": "pdf"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        page_text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Department of Agriculture", page_text)
        self.assertIn("Regional Field Office No. IV-A", page_text)
        self.assertIn("FARMER MASTER LIST", page_text)

    def test_admin_downloaded_pdf_uses_the_same_official_da_header(self):
        from pypdf import PdfReader

        administrator = get_user_model().objects.create_user(
            username="pdf-reports-admin",
            password="StrongPass123!",
            role="ADMIN",
            is_active=True,
        )
        self.client.force_login(administrator)
        response = self.client.post(
            reverse("reports:home"),
            {"report_type": "system_overview", "date_range": "all", "format": "pdf"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        page_text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Department of Agriculture", page_text)
        self.assertIn("Regional Field Office No. IV-A", page_text)
        self.assertIn("SYSTEM OVERVIEW", page_text)

    def test_management_table_pdf_uses_the_same_official_da_header(self):
        from pypdf import PdfReader

        response = generate_table_export(
            "Inventory Movement Register",
            ["Reference", "Item", "Quantity"],
            [["MOV-0001", "Certified Rice Seed", "10 bags"]],
            "pdf",
        )

        page_text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Department of Agriculture", page_text)
        self.assertIn("INVENTORY MOVEMENT REGISTER", page_text)

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
        self.assertContains(response, '<span class="analytics-kpi-icon"')

    def test_one_page_reports_preserves_report_builder(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"), {"analytics_tab": "reports"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report Filters")
        self.assertContains(response, 'name="report_type"')
        self.assertContains(response, 'name="date_range"')
        self.assertContains(response, 'name="barangay"')
        self.assertContains(response, 'name="commodity"')
        self.assertContains(response, 'name="format"')
        self.assertContains(response, "Download Report")

    def test_generated_report_preview_omits_redundant_filtered_analytics_cards(self):
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
        self.assertNotContains(response, "Filtered Report Analytics")
        self.assertNotContains(response, "Descriptive totals calculated from the same records")
        self.assertContains(response, "FARMER MASTER LIST")

    def test_registry_tabs_show_their_own_analytics(self):
        self.client.force_login(self.staff)
        for key, title in (("farmers", "Farmer Statistics"), ("parcels", "Total Parcels"), ("commodities", "Commodity Records")):
            with self.subTest(tab=key):
                response = self.client.get(reverse("reports:home"), {"analytics_tab": key})
                self.assertEqual(response.context["analytics_tab"], key)
                self.assertEqual(response.context["descriptive"]["tab"], key)
                self.assertContains(response, title)
                self.assertContains(response, f'name="analytics_tab" value="{key}"')
                for other_key, other_title in (("farmers", "Farmer Statistics"), ("parcels", "Total Parcels"), ("commodities", "Commodity Records")):
                    if other_key != key:
                        self.assertNotContains(response, other_title)

    def test_each_analytics_measure_uses_an_appropriate_visual(self):
        self.client.force_login(self.staff)
        farmers = self.client.get(reverse("reports:home"), {"analytics_tab": "farmers"})
        self.assertContains(farmers, 'aria-label="Farmers by Barangay bar chart"')
        for tab, title in (("parcels", "Barangays with the Most Farm Parcels"), ("commodities", "Most Planted or Raised Commodities")):
            page = self.client.get(reverse("reports:home"), {"analytics_tab": tab})
            self.assertContains(page, f'aria-label="{title} bar chart"')
        self.assertContains(farmers, "Compare farmer records")
        requests = self.client.get(reverse("reports:home"), {"analytics_tab": "requests"})
        self.assertContains(requests, "Request Status by Month")
        self.assertNotContains(requests, "Recent Requests")
        self.assertContains(requests, 'aria-label="Service Requests Over Time line chart"')
        interventions = self.client.get(reverse("reports:home"), {"analytics_tab": "interventions"})
        self.assertContains(interventions, 'aria-label="Interventions Given by Month line chart"')
        inventory = self.client.get(reverse("reports:home"), {"analytics_tab": "inventory"})
        self.assertContains(inventory, 'aria-label="Inventory Movement Over Time line chart"')

    def test_monthly_trends_include_empty_calendar_months(self):
        first = Farmer.objects.create(first_name="January", last_name="Trend")
        last = Farmer.objects.create(first_name="March", last_name="Trend")
        Farmer.objects.filter(pk=first.pk).update(created_at=timezone.make_aware(datetime(2025, 1, 15, 12)))
        Farmer.objects.filter(pk=last.pk).update(created_at=timezone.make_aware(datetime(2025, 3, 15, 12)))
        series = _monthly_series(Farmer.objects.filter(pk__in=[first.pk, last.pk]), "created_at")
        self.assertEqual([point["value"] for point in series["points"]], [1, 0, 1])
        self.assertEqual([point["label"] for point in series["points"]], ["Jan 2025", "Feb 2025", "Mar 2025"])
        self.assertEqual(series["years"], [{"year": 2025, "months": 3}])
        Farmer.objects.filter(pk=last.pk).update(created_at=timezone.make_aware(datetime(2026, 3, 15, 12)))
        queryset = Farmer.objects.filter(pk__in=[first.pk, last.pk])
        all_months = _monthly_series(queryset, "created_at")
        self.assertEqual(len(all_months["points"]), 15)
        self.assertEqual(sum(point["value"] for point in all_months["points"]), 2)
        self.assertEqual(len(_monthly_series(queryset, "created_at", limit=3)["points"]), 3)

    def test_bar_chart_axis_shows_months_with_one_shared_year_label(self):
        series = _monthly_series(Farmer.objects.all(), "created_at")

        self.assertEqual(len(series["points"][0]["month_label"]), 3)
        self.assertNotIn(" ", series["points"][0]["month_label"])
        self.assertEqual(series["period_label"], str(date.today().year))

    def test_analytics_filter_shares_the_tab_row_and_intervention_summary_follows_chart(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"), {"analytics_tab": "interventions"})
        html = response.content.decode()

        self.assertContains(response, 'aria-label="Reports and analytics sections"', count=1)
        self.assertLess(html.index("Interventions Given by Month"), html.index("INTERVENTION DISTRIBUTION SUMMARY"))
        self.assertNotContains(response, "How to read this summary")

        reports = self.client.get(reverse("reports:home"))
        self.assertContains(reports, 'class="analytics-filter-toolbar', count=1)

    def test_one_page_analytics_filter_contains_all_relevant_fields(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"))
        self.assertContains(response, "Filter All Analytics")
        self.assertContains(response, 'data-filter-popover')
        self.assertContains(response, 'name="analytics_barangay"')
        self.assertContains(response, 'name="analytics_commodity"')
        self.assertContains(response, 'name="analytics_request_status"')
        self.assertContains(response, 'name="analytics_request_priority"')
        self.assertContains(response, 'name="analytics_intervention_type"')
        self.assertContains(response, 'name="analytics_inventory_category"')
        self.assertContains(response, 'name="analytics_inventory_movement_type"')

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

    def test_duplicate_scan_keeps_large_common_name_buckets_reviewable(self):
        Farmer.objects.bulk_create(
            [
                Farmer(
                    first_name=f"Maria {index:03d}",
                    last_name="Santos",
                    barangay="Bagong Pook",
                    is_active=True,
                )
                for index in range(70)
            ]
        )
        left = Farmer.objects.create(
            first_name="Maria Duplicate",
            middle_name="Reyes",
            last_name="Santos",
            barangay="Alupay",
            birth_date=date(1988, 4, 12),
            is_active=True,
        )
        right = Farmer.objects.create(
            first_name="Maria Duplicate",
            middle_name="Reyes",
            last_name="Santos",
            barangay="Alupay",
            birth_date=date(1988, 4, 12),
            is_active=True,
        )

        result = find_system_duplicate_pairs(use_cache=False)

        candidate_ids = {
            frozenset((pair["left_pk"], pair["right_pk"]))
            for pair in result["pairs"]
        }
        self.assertIn(frozenset((left.pk, right.pk)), candidate_ids)


class BarangayBarTests(TestCase):
    def test_all_barangays_and_zero_counts_share_one_scale(self):
        from apps.common.constants import ROSARIO_BARANGAYS
        Farmer.objects.create(first_name="Ana", last_name="Santos", barangay="Bagong Pook", is_active=True)
        series = descriptive_analytics("farmers")["farmer_barangay_series"]
        self.assertEqual([point["label"] for point in series["points"]], list(ROSARIO_BARANGAYS))
        self.assertEqual(sum(point["value"] for point in series["points"]), 1)
        self.assertEqual(next(point for point in series["points"] if point["label"] == "Bagong Pook")["percent"], 100)
        self.assertEqual(series["period_label"], str(date.today().year))


class UpdatedReportChartsTests(TestCase):
    def test_monthly_status_counts_use_receipt_month_include_gaps_and_share_scale(self):
        from django.utils import timezone
        from datetime import datetime
        from apps.service_requests.models import ServiceRequest
        from apps.service_catalog.models import ServiceCatalog
        from apps.reports.analytics import _monthly_request_status_series
        farmer = Farmer.objects.create(first_name="Ana", last_name="Santos", barangay="Bulihan")
        service = ServiceCatalog.objects.create(name="Chart assistance", code="CHART", category="Farm Inputs", description="Test", processing_time="1 day")
        for year, month, status in ((2025, 12, "PENDING"), (2026, 2, "COMPLETED"), (2026, 2, "COMPLETED"), (2026, 2, "IN_PROGRESS")):
            request = ServiceRequest.objects.create(farmer=farmer, service=service, status=status)
            ServiceRequest.objects.filter(pk=request.pk).update(created_at=timezone.make_aware(datetime(year, month, 15)))
        series = _monthly_request_status_series(ServiceRequest.objects.all())
        self.assertEqual([month["label"] for month in series["points"]], ["Dec 2025", "Jan 2026", "Feb 2026"])
        self.assertEqual(series["years"], [{"year": 2025, "months": 1}, {"year": 2026, "months": 2}])
        self.assertEqual(series["peak"], 2)
        self.assertTrue(all(status["value"] == 0 for status in series["points"][1]["statuses"]))
        february = {item["key"]: item for item in series["points"][2]["statuses"]}
        self.assertEqual((february["COMPLETED"]["value"], february["COMPLETED"]["percent"]), (2, 100))
        self.assertEqual(february["IN_PROGRESS"]["percent"], 50)
        self.assertEqual(february["CANCELLED"]["value"], 0)
        empty = _monthly_request_status_series(ServiceRequest.objects.none())
        self.assertEqual(empty["points"], [])

    def test_intervention_comparison_uses_shared_scale(self):
        from apps.reports.analytics import _categorical_dual_series
        rows = [{"label": "Seeds", "value": 2, "farmers": 10}, {"label": "Training", "value": 1, "farmers": 1}]
        series = _categorical_dual_series(rows, rows, first_key="value", second_key="farmers", shared_scale=True)
        self.assertEqual(series["first_peak"], series["second_peak"])
        self.assertEqual(series["first_peak"], 10)
        same_counts = series["points"][1]
        self.assertEqual(same_counts["first_y"], same_counts["second_y"])
        self.assertEqual(series["points"][0]["second_y"], 15)
        self.assertEqual([point["x"] for point in series["points"]], [25, 75])

    def test_report_generator_has_live_summary_cards(self):
        staff = get_user_model().objects.create_user(username="report-card-staff", role="STAFF")
        Farmer.objects.create(first_name="Ana", last_name="Santos", barangay="Bulihan", is_active=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("reports:home"), {"analytics_tab": "reports"})
        self.assertContains(response, 'aria-label="Report data summary"')
        self.assertContains(response, "Available report types")
        self.assertEqual(response.context["farmers"], 1)
        filtered = self.client.get(reverse("reports:home"), {"analytics_tab": "reports", "report_type": "farmer_master", "barangay": "Alupay", "date_range": "all"})
        self.assertContains(filtered, "Matching report rows")
        self.assertEqual(filtered.context["report_preview"]["total_rows"], 0)
        self.assertEqual(filtered.context["farmers"], 0)
