import gzip
import json
import tempfile
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.activity_logs.models import ActivityLog
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.forms import (
    CropRegistrationFormSet,
    DocumentRegistrationFormSet,
    FarmerRegistrationForm,
    ParcelRegistrationFormSet,
)
from apps.farmers.models import Farmer
from apps.reports.export import build_report
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.forms import ServiceRequestForm
from apps.service_requests.models import ServiceRequest


class FMISRequirementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user(username="admin", password="StrongPass123!", role="ADMIN", email="admin@example.com")
        cls.staff = User.objects.create_user(username="staff", password="StrongPass123!", role="STAFF", email="staff@example.com")
        cls.farmer = Farmer.objects.create(
            first_name="Ana", last_name="Santos", sex="FEMALE", birth_date=date(1980, 1, 2),
            place_of_birth="Rosario", mother_maiden_name="Reyes", house_lot_purok="Purok 1",
            barangay="Bulihan", phone_number="09171234567", civil_status="SINGLE",
            valid_id_type="National ID", valid_id_number="ID-001", livelihood="FARMER",
            activities="FARMER_CROPS", rsbsa_number="RSBSA-001", consent_given=True,
            remarks="Follow up before seed distribution.",
        )
        cls.parcel = FarmParcel.objects.create(
            farmer=cls.farmer, parcel_name="North Field", barangay="Bulihan",
            area_hectares=Decimal("2.50"), ownership_type="OWNED",
        )
        cls.crop = CropRecord.objects.create(
            parcel=cls.parcel, crop_type="Rice", cropping_schedule="Wet season",
            area_hectares=Decimal("2.00"), planting_date=date.today(),
        )
        cls.service = ServiceCatalog.objects.create(
            name="Seed Distribution", code="SEED", category="Farm Inputs",
            description="Qualified seed distribution", processing_time="3 days",
        )

    def test_public_legal_pages_and_login_are_available(self):
        for name in ("authentication:landing", "authentication:login", "authentication:privacy", "authentication:terms"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
        self.assertContains(self.client.get(reverse("authentication:privacy")), "Information collected")

    def test_authentication_accepts_valid_credentials_and_rejects_invalid(self):
        response = self.client.post(reverse("authentication:login"), {"username": "staff", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("authentication:login"), {"username": "staff", "password": "StrongPass123!"})
        self.assertEqual(response.status_code, 302)

    def test_role_boundaries_are_enforced(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("farmers:list"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("accounts:list"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))
        self.assertEqual(self.client.get(reverse("farmers:list")).status_code, 200)

    def test_idle_session_timeout_logs_user_out(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session["fmis_last_activity"] = int(time.time()) - 901
        session.save()
        cache.set("fmis:session-timeout-minutes", 15, 60)
        response = self.client.get(reverse("dashboard:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("authentication:login"), response.url)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_valid_id_is_rejected(self):
        form = FarmerRegistrationForm(data={
            "last_name": "Santos", "first_name": "Ana", "sex": "FEMALE", "birth_date": "1980-01-02",
            "place_of_birth": "Rosario", "mother_maiden_name": "Reyes", "house_lot_purok": "Purok 2",
            "barangay": "Bulihan", "city_municipality": "Rosario", "province": "Batangas",
            "region": "CALABARZON Region IV-A", "phone_number": "09170000000", "civil_status": "SINGLE",
            "valid_id_type": "National ID", "valid_id_number": "ID-001", "livelihood": "FARMER",
            "activities": ["FARMER_CROPS"], "consent_given": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("already linked", form.errors["valid_id_number"][0])

    def test_invalid_service_request_is_rejected(self):
        form = ServiceRequestForm(data={
            "farmer": self.farmer.pk, "service": self.service.pk, "subject": "No",
            "priority": "MEDIUM", "status": "PENDING", "notes": "", "assigned_to": self.staff.pk,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("at least 5", form.errors["subject"][0])

    def test_staff_can_create_and_view_service_request(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("service_requests:create"), {
            "farmer": self.farmer.pk, "service": self.service.pk, "subject": "Request certified rice seeds",
            "priority": "HIGH", "status": "PENDING", "notes": "For wet season", "assigned_to": self.staff.pk,
        })
        self.assertRedirects(response, reverse("service_requests:list"))
        request_record = ServiceRequest.objects.get()
        self.assertEqual(self.client.get(reverse("service_requests:detail", args=[request_record.pk])).status_code, 200)

    def test_farmer_records_remarks_and_commodity_are_visible(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
        self.assertContains(response, "Follow up before seed distribution")
        parcel_response = self.client.get(reverse("farm_parcels:detail", args=[self.parcel.pk]))
        self.assertContains(parcel_response, "Rice")

    def test_parcel_table_hides_rsbsa_column_and_map_can_focus_saved_farmer(self):
        self.client.force_login(self.staff)
        parcel_list = self.client.get(reverse("farm_parcels:list"))
        self.assertEqual(parcel_list.status_code, 200)
        self.assertNotContains(parcel_list, "RSBSA Record")

        self.farmer.location_coordinates = "13.8467000, 121.2060000"
        self.farmer.save(update_fields=["location_coordinates"])
        map_response = self.client.get(reverse("farm_parcels:map"))
        self.assertEqual(map_response.status_code, 200)
        self.assertEqual(map_response.context["mapped_count"], 1)
        self.assertEqual(map_response.context["map_markers"][0]["id"], self.farmer.pk)
        self.assertContains(map_response, "markerByFarmer")
        self.assertContains(map_response, "Location Already Pinned")
        self.assertContains(map_response, "farmerMarker.openPopup()")

    def test_farmer_list_displays_calculated_age(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<th>Age</th>", html=True)
        expected_age = date.today().year - self.farmer.birth_date.year - (
            (date.today().month, date.today().day)
            < (self.farmer.birth_date.month, self.farmer.birth_date.day)
        )
        self.assertEqual(self.farmer.age, expected_age)

    def test_registration_starts_with_one_row_and_validates_added_rows(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:create"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["parcel_formset"].total_form_count(), 1)
        self.assertEqual(response.context["crop_formset"].total_form_count(), 1)
        self.assertEqual(response.context["document_formset"].total_form_count(), 1)

        parcel_formset = ParcelRegistrationFormSet({
            "parcels-TOTAL_FORMS": "2", "parcels-INITIAL_FORMS": "0",
            "parcels-MIN_NUM_FORMS": "1", "parcels-MAX_NUM_FORMS": "1000",
            "parcels-0-not_applicable": "on",
        }, prefix="parcels")
        self.assertFalse(parcel_formset.is_valid())
        self.assertTrue(parcel_formset.forms[1].errors)

        crop_formset = CropRegistrationFormSet({
            "crops-TOTAL_FORMS": "2", "crops-INITIAL_FORMS": "0",
            "crops-MIN_NUM_FORMS": "1", "crops-MAX_NUM_FORMS": "1000",
            "crops-0-not_applicable": "on",
        }, prefix="crops")
        self.assertFalse(crop_formset.is_valid())
        self.assertTrue(crop_formset.forms[1].errors)

        valid_id = SimpleUploadedFile("valid-id.png", b"\x89PNG\r\n\x1a\nFMIS", content_type="image/png")
        document_formset = DocumentRegistrationFormSet({
            "documents-TOTAL_FORMS": "2", "documents-INITIAL_FORMS": "0",
            "documents-MIN_NUM_FORMS": "1", "documents-MAX_NUM_FORMS": "1000",
            "documents-0-document_type": "VALID_ID", "documents-0-description": "Valid ID",
        }, {"documents-0-file": valid_id}, prefix="documents")
        self.assertFalse(document_formset.is_valid())
        self.assertTrue(document_formset.forms[1].errors)

    def test_filtered_commodity_per_parcel_report(self):
        title, headers, rows = build_report("commodity_per_parcel", "all", {"barangay": "Bulihan", "commodity": "Rice"})
        self.assertEqual(title, "Commodity per Farm Parcel")
        self.assertIn("Commodity", headers)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], "Rice")
        _, _, excluded = build_report("commodity_per_parcel", "all", {"barangay": "Alupay", "commodity": "Rice"})
        self.assertEqual(excluded, [])

    def test_reports_export_csv_and_validate_filters(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("reports:home"), {
            "report_type": "farmer_master", "format": "csv", "date_range": "all",
            "barangay": "Bulihan", "commodity": "Rice", "year": str(date.today().year), "status": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Follow up before seed distribution", response.content.decode("utf-8-sig"))
        bad = self.client.post(reverse("reports:home"), {
            "report_type": "farmer_master", "format": "csv", "date_range": "all", "barangay": "Outside Rosario",
        })
        self.assertEqual(bad.status_code, 400)

    def test_report_graphs_and_table_use_selected_database_filters(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("reports:home"), {
            "report_type": "crop_summary", "date_range": "all",
            "barangay": "Bulihan", "commodity": "Rice", "year": "", "status": "",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report_preview"]["total_rows"], 1)
        self.assertEqual(response.context["report_preview"]["chart"][0]["label"], "Rice")
        self.assertEqual(response.context["crops"], 1)
        self.assertNotContains(response, "Update Graphs")
        self.assertContains(response, "Download Report")
        self.assertContains(response, "showSelectedReport")
        self.assertContains(response, "Crop Production Summary")

        empty = self.client.get(reverse("reports:home"), {
            "report_type": "crop_summary", "date_range": "all",
            "barangay": "Alupay", "commodity": "Rice", "year": "", "status": "",
        })
        self.assertEqual(empty.context["report_preview"]["total_rows"], 0)
        self.assertEqual(empty.context["crops"], 0)
        self.assertContains(empty, "No records match the selected filters")

    def test_dashboard_graphs_reflect_current_database_records(self):
        ServiceRequest.objects.create(
            farmer=self.farmer, service=self.service, subject="Request chart verification",
            priority="HIGH", status="PENDING", assigned_to=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["request_six_month_total"], 1)
        self.assertEqual(response.context["request_status"]["pending"], 1)
        self.assertContains(response, "1 total database records")

        ActivityLog.objects.create(
            actor=self.admin, action="GRAPH_TEST", path="/dashboard/admin/",
            title="Dashboard graph verification", module="Dashboard", status="Success",
        )
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse("dashboard:admin_home"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertGreaterEqual(admin_response.context["activity_week_total"], 1)
        self.assertContains(admin_response, "System Activity")

    def test_settings_accepts_unchanged_legacy_profile_without_names_or_email(self):
        self.admin.first_name = ""
        self.admin.last_name = ""
        self.admin.email = ""
        self.admin.save(update_fields=["first_name", "last_name", "email"])
        self.client.force_login(self.admin)
        response = self.client.post(reverse("settings_page:home"), {
            "first_name": "", "last_name": "", "email": "", "phone_number": "",
            "theme": "light", "primary_color": "#008552",
            "email_notifications": "on", "in_app_notifications": "on", "weekly_summary": "on",
            "system_name": "FMIS - Office of Agriculture", "timezone": "Asia/Manila",
            "default_language": "English", "session_timeout": "15", "automated_backups": "on",
        })
        self.assertRedirects(response, reverse("settings_page:home"))

    def test_report_query_count_remains_bounded(self):
        with CaptureQueriesContext(connection) as captured:
            build_report("farmer_master", "all", {"commodity": "Rice"})
        self.assertLessEqual(len(captured), 5)

    def test_key_pages_respond_within_two_seconds_in_test_environment(self):
        self.client.force_login(self.staff)
        for url in (reverse("dashboard:home"), reverse("farmers:list"), reverse("reports:home")):
            started = time.perf_counter()
            response = self.client.get(url, follow=True)
            elapsed = time.perf_counter() - started
            self.assertEqual(response.status_code, 200)
            self.assertLess(elapsed, 2.0, f"{url} took {elapsed:.3f} seconds")

    def test_backup_command_creates_verified_compressed_fixture(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            call_command("backup_fmis", output_dir=temp_dir, verbosity=0)
            backups = list(Path(temp_dir).glob("fmis-backup-*.json.gz"))
            self.assertEqual(len(backups), 1)
            with gzip.open(backups[0], "rt", encoding="utf-8") as backup_file:
                payload = json.load(backup_file)
            self.assertTrue(any(item["model"] == "farmers.farmer" for item in payload))

    def test_administrator_can_trigger_and_download_manual_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(BACKUP_ROOT=Path(temp_dir)):
            self.client.force_login(self.admin)
            response = self.client.post(reverse("settings_page:manual_backup"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/gzip")
            self.assertEqual(response["X-FMIS-Backup-Status"], "verified")
            self.assertIn("attachment", response["Content-Disposition"])
            self.assertEqual(len(list(Path(temp_dir).glob("fmis-backup-*.json.gz"))), 1)
            self.assertGreater(len(b"".join(response.streaming_content)), 0)
            response.close()

            self.client.force_login(self.staff)
            denied = self.client.post(reverse("settings_page:manual_backup"))
            self.assertEqual(denied.status_code, 302)
            self.assertEqual(denied.url, reverse("dashboard:home"))
