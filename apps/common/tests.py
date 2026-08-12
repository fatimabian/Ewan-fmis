import base64
import gzip
import json
import re
import tempfile
import time
from unittest.mock import Mock, patch
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.activity_logs.models import ActivityLog
from apps.activity_logs.middleware import ActivityLogMiddleware
from apps.activity_logs.services import log_activity
from apps.accounts.forms import AccountForm
from apps.crops.forms import CropRecordForm
from apps.crops.models import CropRecord
from apps.dashboard.services import _crop_recommendation
from apps.farm_parcels.models import FarmParcel
from apps.farmers.forms import (
    CropRegistrationFormSet,
    DocumentRegistrationFormSet,
    FarmerRegistrationForm,
    ParcelRegistrationFormSet,
)
from apps.farmers.models import Farmer, FarmerUpdateHistory
from apps.reports.export import build_report
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.forms import ServiceRequestForm
from apps.service_requests.models import ServiceRequest


class FMISRequirementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user(
            username="admin", password="StrongPass123!", role="ADMIN", email="admin@example.com"
        )
        cls.staff = User.objects.create_user(
            username="staff", password="StrongPass123!", role="STAFF", email="staff@example.com"
        )
        cls.farmer = Farmer.objects.create(
            first_name="Ana",
            last_name="Santos",
            sex="FEMALE",
            birth_date=date(1980, 1, 2),
            place_of_birth="Rosario",
            mother_maiden_name="Reyes",
            house_lot_purok="Purok 1",
            barangay="Bulihan",
            phone_number="09171234567",
            civil_status="SINGLE",
            valid_id_type="National ID",
            valid_id_number="ID-001",
            livelihood="FARMER",
            activities="FARMER_CROPS",
            rsbsa_number="RSBSA-001",
            consent_given=True,
            remarks="Follow up before seed distribution.",
        )
        cls.parcel = FarmParcel.objects.create(
            farmer=cls.farmer,
            parcel_name="North Field",
            barangay="Bulihan",
            area_hectares=Decimal("2.50"),
            ownership_type="OWNED",
        )
        cls.crop = CropRecord.objects.create(
            parcel=cls.parcel,
            crop_type="Rice",
            area_hectares=Decimal("2.00"),
            planting_date=date.today(),
        )
        cls.service = ServiceCatalog.objects.create(
            name="Seed Distribution",
            code="SEED",
            category="Farm Inputs",
            description="Qualified seed distribution",
            processing_time="3 days",
        )

    def test_public_legal_pages_and_login_are_available(self):
        for name in (
            "authentication:landing",
            "authentication:login",
            "authentication:privacy",
            "authentication:terms",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
        self.assertContains(
            self.client.get(reverse("authentication:privacy")), "Information collected"
        )
        landing = self.client.get(reverse("authentication:landing"))
        self.assertContains(landing, "rosario-rice-fields-v2.webp")
        self.assertContains(landing, "rosario-seed-support-v2.webp")
        self.assertContains(landing, "rosario-field-consultation-v2.webp")
        self.assertContains(landing, "data-carousel-next")
        self.assertContains(landing, "data-service-next")
        self.assertContains(landing, "feature-toggle")
        self.assertContains(landing, "landingProgress")
        self.assertContains(landing, "setInterval(() => showSlide(activeSlide + 1), 5000)")
        self.assertContains(landing, "startServiceCarousel")
        self.assertContains(landing, "advanceServices")

    def test_application_header_shows_only_the_current_page_title(self):
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse("service_catalog:list"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "Service Catalogs")
        self.assertNotContains(admin_response, "Administrator Workspace")

        self.client.force_login(self.staff)
        staff_response = self.client.get(reverse("farmers:list"))
        self.assertEqual(staff_response.status_code, 200)
        self.assertNotContains(staff_response, "Staff Workspace")

    def test_password_fields_have_show_and_hide_controls(self):
        landing = self.client.get(reverse("authentication:landing"))
        self.assertContains(landing, "data-password-toggle", count=1)
        self.assertContains(landing, 'aria-controls="id_password"')
        self.assertContains(landing, "password-toggle.js")

        login = self.client.get(reverse("authentication:login"))
        self.assertContains(login, "data-password-toggle", count=1)
        self.assertContains(login, 'aria-controls="id_password"')

        self.client.force_login(self.admin)
        account_form = self.client.get(reverse("accounts:create"))
        self.assertEqual(account_form.status_code, 200)
        self.assertContains(account_form, "data-password-toggle", count=2)
        self.assertContains(account_form, 'class="account-password-toggle"', count=2)
        self.assertContains(account_form, 'aria-controls="id_password1"')
        self.assertContains(account_form, 'aria-controls="id_password2"')

    def test_authentication_accepts_valid_credentials_and_rejects_invalid(self):
        response = self.client.post(
            reverse("authentication:login"), {"username": "staff", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "auth-inline-error")
        self.assertContains(response, "The username or password is incorrect.")
        self.assertContains(response, "has-error", count=2)
        self.assertContains(response, "novalidate")
        self.assertNotContains(response, "authMessage")
        self.assertNotContains(response, "form-validation.js")

        landing_error = self.client.post(
            reverse("authentication:landing"),
            {"username": "staff", "password": "wrong"},
        )
        self.assertEqual(landing_error.status_code, 200)
        self.assertContains(landing_error, "landing-field-error")
        self.assertContains(landing_error, "The username or password is incorrect.")
        self.assertContains(landing_error, "has-error", count=2)
        self.assertContains(landing_error, "novalidate")
        response = self.client.post(
            reverse("authentication:login"), {"username": "staff", "password": "StrongPass123!"}
        )
        self.assertEqual(response.status_code, 302)

    def test_new_account_is_staff_and_waits_for_email_activation(self):
        form = AccountForm(
            data={
                "username": "newstaff",
                "email": "newstaff@example.com",
                "phone_number": "09175550123",
                "password1": "Ready4Field!Secure",
                "password2": "Ready4Field!Secure",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.role, "STAFF")
        self.assertFalse(user.is_active)
        self.assertTrue(user.activation_pending)
        self.assertEqual(user.first_name, "")
        self.assertEqual(user.last_name, "")

    def test_pending_staff_activates_with_first_login_email_otp(self):
        User = get_user_model()
        pending = User.objects.create_user(
            username="pendingstaff",
            email="pending@example.com",
            phone_number="09175550456",
            password="Ready4Field!Secure",
            role="STAFF",
            is_active=False,
            activation_pending=True,
        )
        response = self.client.post(
            reverse("authentication:login"),
            {"username": pending.username, "password": "Ready4Field!Secure"},
        )
        self.assertRedirects(response, reverse("authentication:activate_account"))
        self.assertEqual(len(mail.outbox), 1)
        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group(0)

        activation_page = self.client.get(reverse("authentication:activate_account"))
        self.assertContains(activation_page, "Confirm your staff account.")
        self.assertContains(activation_page, "Check your email")
        self.assertContains(activation_page, "pe*****@example.com")
        self.assertContains(activation_page, "Five verification attempts are allowed")

        response = self.client.post(
            reverse("authentication:activate_account"),
            {"code": code},
        )
        self.assertRedirects(response, reverse("dashboard:staff_home"))
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertFalse(pending.activation_pending)

    def test_landing_page_embedded_login_uses_secure_authentication_flow(self):
        response = self.client.post(
            reverse("authentication:landing"),
            {
                "username": "staff",
                "password": "StrongPass123!",
                "remember_me": "on",
            },
        )
        self.assertRedirects(response, reverse("dashboard:staff_home"))
        self.assertGreater(self.client.session.get_expiry_age(), 24 * 60 * 60)

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
        self.assertTrue(response.url.startswith(reverse("authentication:landing")))
        self.assertIn("next=%2Fdashboard%2F", response.url)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_valid_id_is_rejected(self):
        form = FarmerRegistrationForm(
            data={
                "last_name": "Santos",
                "first_name": "Ana",
                "sex": "FEMALE",
                "birth_date": "1980-01-02",
                "place_of_birth": "Rosario",
                "mother_maiden_name": "Reyes",
                "house_lot_purok": "Purok 2",
                "barangay": "Bulihan",
                "city_municipality": "Rosario",
                "province": "Batangas",
                "region": "CALABARZON Region IV-A",
                "phone_number": "09170000000",
                "civil_status": "SINGLE",
                "valid_id_type": "National ID",
                "valid_id_number": "ID-001",
                "livelihood": "FARMER",
                "activities": ["FARMER_CROPS"],
                "consent_given": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("already linked", form.errors["valid_id_number"][0])

    def test_invalid_service_request_is_rejected(self):
        form = ServiceRequestForm(
            data={
                "farmer": self.farmer.pk,
                "service": self.service.pk,
                "subject": "No",
                "priority": "MEDIUM",
                "status": "PENDING",
                "notes": "",
                "assigned_to": self.staff.pk,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("at least 5", form.errors["subject"][0])

    def test_staff_can_create_and_view_service_request(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("service_requests:create"),
            {
                "farmer": self.farmer.pk,
                "service": self.service.pk,
                "subject": "Request certified rice seeds",
                "priority": "HIGH",
                "status": "PENDING",
                "notes": "For wet season",
                "assigned_to": self.staff.pk,
            },
        )
        self.assertRedirects(response, reverse("service_requests:list"))
        request_record = ServiceRequest.objects.get()
        self.assertEqual(
            self.client.get(
                reverse("service_requests:detail", args=[request_record.pk])
            ).status_code,
            200,
        )

    def test_farmer_records_remarks_and_commodity_are_visible(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
        self.assertContains(response, "Follow up before seed distribution")
        parcel_response = self.client.get(reverse("farm_parcels:detail", args=[self.parcel.pk]))
        self.assertContains(parcel_response, "Rice")

    def test_slip_a_preserves_before_after_values_and_last_editor(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("farmers:edit", args=[self.farmer.pk]),
            {
                "last_name": "Santos",
                "first_name": "Ana",
                "middle_name": "",
                "extension_name": "",
                "sex": "FEMALE",
                "birth_date": "1980-01-02",
                "place_of_birth": "Rosario",
                "mother_maiden_name": "Reyes",
                "house_lot_purok": "Purok 1",
                "street_sitio": "",
                "barangay": "Bulihan",
                "phone_number": "09179999999",
                "email": "",
                "civil_status": "SINGLE",
                "spouse_name": "",
                "highest_education": "",
                "valid_id_type": "National ID",
                "valid_id_number": "ID-001",
                "religion": "",
                "indigenous_group": "",
                "fca_membership": "",
                "remarks": "Follow up before seed distribution.",
                "location_coordinates": "",
                "transaction_code": "SLIP-A-001",
                "change_reason": "CORRECTION",
                "update_remarks": "Corrected contact number",
                "registrant_declaration": "on",
            },
        )
        self.assertEqual(
            response.status_code,
            302,
            getattr(response.context.get("form"), "errors", "") if response.context else "",
        )
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.phone_number, "09179999999")
        self.assertEqual(self.farmer.last_updated_by, self.staff)
        history = FarmerUpdateHistory.objects.get(farmer=self.farmer)
        self.assertEqual(history.update_type, "SLIP_A")
        phone_change = next(
            change for change in history.changes if change["field"] == "Personal / Phone Number"
        )
        self.assertEqual(phone_change["before"], "09171234567")
        self.assertEqual(phone_change["after"], "09179999999")
        detail = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
        self.assertContains(detail, "SLIP-A-001")
        self.assertContains(detail, self.staff.display_name)
        farmer_list = self.client.get(reverse("farmers:list"))
        self.assertContains(farmer_list, "Last Updated By")
        self.assertContains(farmer_list, "Latest Change")
        self.assertContains(farmer_list, self.staff.display_name)
        self.assertContains(farmer_list, "Personal / Phone Number")

    def test_slip_b_is_separate_and_contains_official_parcel_workflow(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:slip_b", args=[self.farmer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change of Farm Parcel Information")
        self.assertContains(response, "Livelihood and activity / involvement")
        self.assertContains(response, "Edit Parcel &amp; Crops")
        parcel_form = self.client.get(reverse("farm_parcels:edit", args=[self.parcel.pk]))
        for field_name in (
            "cropping_schedule",
            "gpx_status",
            "rotational_tiller",
            "land_owner_rsbsa_number",
            "ownership_document_other",
        ):
            self.assertContains(parcel_form, field_name)

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
        self.assertContains(map_response, "Satellite")
        self.assertContains(map_response, "Terrain")
        self.assertContains(map_response, "maxBounds: rosarioBounds")

    def test_farmer_map_rejects_pins_outside_rosario_batangas(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("farm_parcels:pin_farmer"),
            {
                "farmer_id": self.farmer.pk,
                "latitude": "14.5995",
                "longitude": "120.9842",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("outside Rosario", response.json()["message"])
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.location_coordinates, "")

    def test_staff_can_move_farmer_pin_and_change_is_audited(self):
        self.farmer.location_coordinates = "13.8467000, 121.2060000"
        self.farmer.save(update_fields=["location_coordinates"])
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("farm_parcels:pin_farmer"),
            {
                "farmer_id": self.farmer.pk,
                "latitude": "13.8501000",
                "longitude": "121.2102000",
                "operation": "move",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.location_coordinates, "13.8501000, 121.2102000")
        activity = ActivityLog.objects.get(
            title="Farmer Map Pin Moved",
            target_label=self.farmer.full_name,
        )
        self.assertEqual(activity.actor, self.staff)
        self.assertEqual(activity.details[0]["before"], "13.8467000, 121.2060000")
        self.assertEqual(activity.details[0]["after"], "13.8501000, 121.2102000")

        map_response = self.client.get(reverse("farm_parcels:map"))
        self.assertContains(map_response, "Right-click a green farmer pin to move it")
        self.assertContains(map_response, "Save New Location")

    def test_parcel_form_requires_one_crop_and_validates_only_added_rows(self):
        self.client.force_login(self.staff)
        create_url = reverse("farm_parcels:create")
        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["crop_formset"].total_form_count(), 1)
        self.assertContains(response, "Add Crop")

        base_data = {
            "farmer": self.farmer.pk,
            "barangay": "Bulihan",
            "municipality": "Rosario",
            "province": "Batangas",
            "area_hectares": "1.50",
            "ownership_type": "OWNED",
            "land_type": "UPLAND",
            "farm_type": "Irrigated",
            "is_active": "on",
            "is_rsbsa_recorded": "False",
            "parcel_crops-TOTAL_FORMS": "1",
            "parcel_crops-INITIAL_FORMS": "0",
            "parcel_crops-MIN_NUM_FORMS": "1",
            "parcel_crops-MAX_NUM_FORMS": "1000",
            "parcel_crops-0-crop_type": "Corn",
            "parcel_crops-0-area_hectares": "1.00",
            "parcel_crops-0-is_organic": "False",
            "parcel_crops-0-is_intercrop": "False",
        }
        valid = self.client.post(create_url, base_data)
        self.assertEqual(valid.status_code, 302)
        created_parcel = FarmParcel.objects.exclude(pk=self.parcel.pk).get()
        self.assertEqual(created_parcel.crops.get().crop_type, "Corn")

        invalid_data = {
            **base_data,
            "parcel_crops-TOTAL_FORMS": "2",
            "parcel_crops-1-crop_type": "",
            "parcel_crops-1-area_hectares": "",
        }
        invalid = self.client.post(create_url, invalid_data)
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.context["crop_formset"].forms[1].errors)

    def test_other_crop_requires_specific_name_and_saves_it_to_crop_database(self):
        missing_name = CropRegistrationFormSet(
            {
                "crops-TOTAL_FORMS": "1",
                "crops-INITIAL_FORMS": "0",
                "crops-MIN_NUM_FORMS": "1",
                "crops-MAX_NUM_FORMS": "1000",
                "crops-0-parcel_number": "1",
                "crops-0-crop_type": "Other Crop / Commodity",
                "crops-0-other_crop_name": "",
                "crops-0-area_hectares": "0.50",
                "crops-0-is_organic": "False",
                "crops-0-is_intercrop": "False",
            },
            prefix="crops",
        )
        self.assertFalse(missing_name.is_valid())
        self.assertIn("other_crop_name", missing_name.forms[0].errors)

        crop_form = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Other Crop / Commodity",
                "other_crop_name": "Dragon Fruit",
                "cropping_schedule": "Jan-Mar",
                "area_hectares": "0.50",
                "number_of_heads": "",
                "is_organic": "False",
                "is_intercrop": "False",
                "planting_date": "2026-01-10",
                "harvest_date": "2026-04-10",
            }
        )
        self.assertTrue(crop_form.is_valid(), crop_form.errors)
        crop = crop_form.save()
        self.assertEqual(crop.crop_type, "Dragon Fruit")
        self.assertEqual(
            CropRecord.objects.get(pk=crop.pk).crop_type,
            "Dragon Fruit",
        )

    def test_farmer_list_uses_operational_database_columns(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:list"))
        self.assertEqual(response.status_code, 200)
        for heading in (
            "Farmer ID",
            "Farmer Name",
            "Barangay",
            "Contact Number",
            "Livelihood",
            "Status",
            "Actions",
        ):
            self.assertContains(response, f"<th>{heading}</th>", html=True)
        self.assertNotContains(response, "<th>Age</th>", html=True)
        self.assertNotContains(response, "<th>Sex</th>", html=True)
        self.assertContains(response, self.farmer.record_id)
        self.assertContains(response, self.farmer.list_name)
        self.assertContains(response, self.farmer.phone_number)
        self.assertContains(response, self.farmer.get_livelihood_display())
        self.assertContains(response, '<span class="farmer-status active">Active</span>', html=True)

    def test_spouse_is_required_only_for_married_registrants(self):
        blank_form = FarmerRegistrationForm()
        self.assertFalse(blank_form.fields["spouse_name"].required)
        for fixed_field in ("city_municipality", "province", "region"):
            self.assertTrue(blank_form.fields[fixed_field].disabled)
            self.assertFalse(blank_form.fields[fixed_field].required)

        married_form = FarmerRegistrationForm(data={"civil_status": "MARRIED"})
        self.assertTrue(married_form.fields["spouse_name"].required)
        married_form.is_valid()
        self.assertIn("spouse_name", married_form.errors)

        single_form = FarmerRegistrationForm(data={"civil_status": "SINGLE"})
        self.assertFalse(single_form.fields["spouse_name"].required)

    def test_registration_starts_with_one_row_and_validates_added_rows(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:create"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["parcel_formset"].total_form_count(), 1)
        self.assertEqual(response.context["crop_formset"].total_form_count(), 1)
        self.assertEqual(response.context["document_formset"].total_form_count(), 1)

        parcel_formset = ParcelRegistrationFormSet(
            {
                "parcels-TOTAL_FORMS": "2",
                "parcels-INITIAL_FORMS": "0",
                "parcels-MIN_NUM_FORMS": "1",
                "parcels-MAX_NUM_FORMS": "1000",
                "parcels-0-barangay": "Alupay",
                "parcels-0-municipality": "Rosario",
                "parcels-0-province": "Batangas",
                "parcels-0-area_hectares": "1.50",
                "parcels-0-ownership_type": "OWNED",
                "parcels-0-land_type": "UPLAND",
                "parcels-0-farm_type": "Irrigated",
                "parcels-0-is_rsbsa_recorded": "False",
                "parcels-0-is_active": "True",
            },
            prefix="parcels",
        )
        self.assertFalse(parcel_formset.is_valid())
        self.assertFalse(parcel_formset.forms[0].errors)
        self.assertTrue(parcel_formset.forms[1].errors)

        crop_formset = CropRegistrationFormSet(
            {
                "crops-TOTAL_FORMS": "2",
                "crops-INITIAL_FORMS": "0",
                "crops-MIN_NUM_FORMS": "1",
                "crops-MAX_NUM_FORMS": "1000",
                "crops-0-parcel_number": "1",
                "crops-0-crop_type": "Corn",
                "crops-0-area_hectares": "1.00",
                "crops-0-is_organic": "False",
                "crops-0-is_intercrop": "False",
            },
            prefix="crops",
        )
        self.assertFalse(crop_formset.is_valid())
        self.assertTrue(crop_formset.forms[1].errors)

        valid_id = SimpleUploadedFile(
            "valid-id.png", b"\x89PNG\r\n\x1a\nFMIS", content_type="image/png"
        )
        document_formset = DocumentRegistrationFormSet(
            {
                "documents-TOTAL_FORMS": "2",
                "documents-INITIAL_FORMS": "0",
                "documents-MIN_NUM_FORMS": "1",
                "documents-MAX_NUM_FORMS": "1000",
                "documents-0-document_type": "VALID_ID",
                "documents-0-description": "Valid ID",
            },
            {"documents-0-file": valid_id},
            prefix="documents",
        )
        self.assertFalse(document_formset.is_valid())
        self.assertTrue(document_formset.forms[1].errors)

    def test_filtered_commodity_per_parcel_report(self):
        title, headers, rows = build_report(
            "commodity_per_parcel", "all", {"barangay": "Bulihan", "commodity": "Rice"}
        )
        self.assertEqual(title, "Commodity per Farm Parcel")
        self.assertIn("Commodity", headers)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], "Rice")
        _, _, excluded = build_report(
            "commodity_per_parcel", "all", {"barangay": "Alupay", "commodity": "Rice"}
        )
        self.assertEqual(excluded, [])

    def test_reports_export_csv_and_validate_filters(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("reports:home"),
            {
                "report_type": "farmer_master",
                "format": "csv",
                "date_range": "all",
                "barangay": "Bulihan",
                "commodity": "Rice",
                "year": str(date.today().year),
                "status": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Follow up before seed distribution", response.content.decode("utf-8-sig"))
        bad = self.client.post(
            reverse("reports:home"),
            {
                "report_type": "farmer_master",
                "format": "csv",
                "date_range": "all",
                "barangay": "Outside Rosario",
            },
        )
        self.assertEqual(bad.status_code, 400)

    def test_report_graphs_and_table_use_selected_database_filters(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"),
            {
                "report_type": "crop_summary",
                "date_range": "all",
                "barangay": "Bulihan",
                "commodity": "Rice",
                "year": "",
                "status": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["report_preview"]["total_rows"], 1)
        self.assertEqual(response.context["report_preview"]["chart"][0]["label"], "Rice")
        self.assertEqual(response.context["crops"], 1)
        self.assertNotContains(response, "Update Graphs")
        self.assertContains(response, "Download Report")
        self.assertContains(response, "refreshPreview")
        self.assertContains(response, "Crop Production Summary")

        empty = self.client.get(
            reverse("reports:home"),
            {
                "report_type": "crop_summary",
                "date_range": "all",
                "barangay": "Alupay",
                "commodity": "Rice",
                "year": "",
                "status": "",
            },
        )
        self.assertEqual(empty.context["report_preview"]["total_rows"], 0)
        self.assertEqual(empty.context["crops"], 0)
        self.assertContains(empty, "No records match the selected filters")

    def test_staff_dashboard_uses_rosario_crop_records_and_fixed_weather_location(self):
        ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Request chart verification",
            priority="HIGH",
            status="PENDING",
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["request_status"]["pending"], 1)
        self.assertEqual(response.context["crop_chart"][0]["crop_type"], "Rice")
        self.assertEqual(response.context["crop_chart"][0]["area"], 2.0)
        self.assertEqual(response.context["area_planted"], Decimal("2.00"))
        self.assertNotIn("farmer_statistics", response.context)
        self.assertNotContains(response, "Farmer Statistics")
        self.assertContains(response, "Rosario, Batangas")
        self.assertContains(response, 'data-latitude="13.8442"')
        self.assertContains(response, "Area Planted by Crop")
        self.assertContains(response, "Evidence coverage")
        self.assertContains(response, "baseline score")
        self.assertContains(response, "50% season")
        self.assertEqual(response.context["crop_recommendation"]["crop"], "Rice")
        self.assertEqual(response.context["crop_recommendation"]["confidence"], "Low")
        self.assertNotContains(response, "Inventor")
        self.assertNotContains(response, "Pending Projects")

        reports = self.client.get(reverse("reports:home"))
        self.assertContains(reports, "FARMER STATISTICS")
        self.assertContains(reports, "Female Farmers")
        self.assertContains(reports, "Male Farmers")
        self.assertContains(reports, "PWD Farmers")

        ActivityLog.objects.create(
            actor=self.admin,
            action="GRAPH_TEST",
            path="/dashboard/admin/",
            title="Dashboard graph verification",
            module="Dashboard",
            status="Success",
        )
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse("dashboard:admin_home"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertGreaterEqual(admin_response.context["activity_week_total"], 1)
        self.assertContains(admin_response, "System Activity")
        self.assertContains(admin_response, 'class="activity-line-chart"')
        self.assertContains(admin_response, 'class="activity-line-path"')
        self.assertNotContains(admin_response, 'class="staff-bar-column"')
        self.assertNotContains(admin_response, "Export Dashboard")

    def test_management_tables_export_current_filters_without_report_preview(self):
        ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Filtered seed request",
            priority="HIGH",
            status="PENDING",
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)

        for page_name, dataset in (
            ("farmers:list", "farmers"),
            ("farm_parcels:list", "parcels"),
            ("crops:list", "crops"),
            ("service_requests:list", "requests"),
        ):
            page = self.client.get(reverse(page_name))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "Export filtered records")
            self.assertContains(
                page,
                reverse("reports:management_export", args=[dataset]),
            )
            self.assertNotContains(page, "No report selected yet")

        farmer_export = self.client.get(
            reverse("reports:management_export", args=["farmers"]),
            {"format": "csv", "barangay": "Bulihan"},
        )
        self.assertEqual(farmer_export.status_code, 200)
        self.assertEqual(farmer_export["Content-Type"], "text/csv; charset=utf-8")
        farmer_csv = farmer_export.content.decode("utf-8-sig")
        self.assertIn("Farmer Management List", farmer_csv)
        self.assertIn(self.farmer.record_id, farmer_csv)
        self.assertIn(self.farmer.list_name, farmer_csv)
        self.assertIn("Barangay,Bulihan", farmer_csv)

        parcel_export = self.client.get(
            reverse("reports:management_export", args=["parcels"]),
            {"format": "csv", "ownership": "OWNED", "status": "active"},
        )
        self.assertEqual(parcel_export.status_code, 200)
        self.assertIn(
            "Farm Parcel Management List",
            parcel_export.content.decode("utf-8-sig"),
        )

        crop_export = self.client.get(
            reverse("reports:management_export", args=["crops"]),
            {"format": "pdf", "crop_type": "Rice"},
        )
        self.assertEqual(crop_export.status_code, 200)
        self.assertEqual(crop_export["Content-Type"], "application/pdf")

        request_export = self.client.get(
            reverse("reports:management_export", args=["requests"]),
            {"format": "csv", "status": "PENDING"},
        )
        self.assertEqual(request_export.status_code, 200)
        self.assertIn(
            "Filtered seed request",
            request_export.content.decode("utf-8-sig"),
        )

    def test_crop_planning_baseline_exposes_evidence_strength(self):
        seasonal_only = _crop_recommendation(date(2026, 8, 1), [])
        self.assertEqual(seasonal_only["crop"], "Rice")
        self.assertEqual(seasonal_only["score"], 50)
        self.assertEqual(seasonal_only["confidence"], "Low")
        self.assertIn("seasonal baseline only", seasonal_only["evidence"])

        locally_supported = _crop_recommendation(
            date(2026, 8, 1),
            [
                {
                    "crop_type": "Banana",
                    "area": Decimal("10.00"),
                    "records": 20,
                    "latest_planting": date(2026, 7, 1),
                }
            ],
        )
        self.assertEqual(locally_supported["crop"], "Banana")
        self.assertEqual(locally_supported["confidence"], "High")
        self.assertIn("sample 20/20", locally_supported["evidence"])

    def test_activity_log_accepts_detailed_audit_fields(self):
        activity = log_activity(
            self.staff,
            "POST /farmers/new/",
            "/farmers/new/",
        )
        self.assertEqual(activity.actor, self.staff)
        self.assertEqual(activity.module, "Farmers")
        self.assertEqual(activity.target_label, "")
        self.assertEqual(activity.reason, "")
        self.assertEqual(activity.details, [])

    def test_activity_log_page_loads_registered_pagination_library(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("activity_logs:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activity Log")
        self.assertNotContains(response, "pagination_tags is not a registered tag library")

    def test_in_app_notifications_are_private_linked_and_markable_as_read(self):
        User = get_user_model()
        recipient = User.objects.create_user(
            username="notificationstaff",
            password="Ready4Field!Secure",
            role="STAFF",
            email="notice@example.com",
        )
        activity = log_activity(self.admin, "POST /catalog/new/", "/catalog/new/")

        from apps.notifications.models import Notification
        from apps.settings_page.models import UserPreference

        notification = Notification.objects.get(
            recipient=recipient,
            source_activity=activity,
        )
        self.assertFalse(notification.is_read)
        self.assertIn(self.admin.display_name, notification.message)
        self.assertNotIn("before", notification.message.casefold())
        self.assertNotIn("after", notification.message.casefold())
        self.assertNotIn("reason", notification.message.casefold())
        self.assertEqual(
            notification.url,
            f"{reverse('activity_logs:list')}?highlight={activity.pk}#activity-{activity.pk}",
        )

        self.client.force_login(recipient)
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertContains(dashboard, "notification-count")
        self.assertContains(dashboard, notification.title)
        self.assertEqual(dashboard.context["notification_unread_count"], 1)

        opened = self.client.post(reverse("notifications:open", args=[notification.pk]))
        self.assertRedirects(opened, notification.url, fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)
        self.assertIsNotNone(notification.read_at)

        preference = UserPreference.objects.get(user=recipient)
        preference.in_app_notifications = False
        preference.save(update_fields=("in_app_notifications",))
        log_activity(self.admin, "POST /catalog/new/", "/catalog/new/")
        self.assertEqual(Notification.objects.filter(recipient=recipient).count(), 1)

        settings_page = self.client.get(reverse("settings_page:home"))
        self.assertNotContains(settings_page, "Email Notifications")
        self.assertNotContains(settings_page, "Weekly Summary")
        self.assertContains(settings_page, "In-App Notifications")

    def test_activity_failure_does_not_replace_successful_response(self):
        request = RequestFactory().post("/farmers/new/")
        request.user = self.staff
        middleware = ActivityLogMiddleware(lambda _request: HttpResponse(status=302))
        with patch(
            "apps.activity_logs.services.log_activity",
            side_effect=TypeError("simulated stale activity model"),
        ):
            response = middleware(request)
        self.assertEqual(response.status_code, 302)

    def test_settings_accepts_unchanged_legacy_profile_without_names_or_email(self):
        self.admin.first_name = ""
        self.admin.last_name = ""
        self.admin.email = ""
        self.admin.save(update_fields=["first_name", "last_name", "email"])
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("settings_page:home"),
            {
                "first_name": "",
                "last_name": "",
                "email": "",
                "phone_number": "",
                "theme": "light",
                "primary_color": "#008552",
                "email_notifications": "on",
                "in_app_notifications": "on",
                "weekly_summary": "on",
                "system_name": "FMIS - Office of Agriculture",
                "timezone": "Asia/Manila",
                "default_language": "English",
                "session_timeout": "15",
                "automated_backups": "on",
            },
        )
        self.assertRedirects(response, reverse("settings_page:home"))

    def test_system_theme_is_default_and_resolves_before_page_content(self):
        self.client.force_login(self.staff)
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'data-theme-preference="system"')
        self.assertContains(dashboard, 'prefers-color-scheme: dark')
        self.assertContains(dashboard, "document.documentElement.style.colorScheme")

        settings_page = self.client.get(reverse("settings_page:home"))
        self.assertContains(settings_page, "System (Recommended)")
        self.assertContains(settings_page, "follows your computer's light or dark appearance")

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
        encryption_key = base64.urlsafe_b64encode(b"x" * 32).decode()
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(
            FMIS_BACKUP_ENCRYPTION_KEY=encryption_key,
            BACKUP_AZURE_CONTAINER_URL="",
        ):
            call_command("backup_fmis", output_dir=temp_dir, verbosity=0, force=True)
            backups = list(Path(temp_dir).glob("fmis-backup-*.fmisbak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes()[:11], b"FMISBACKUP1")
            from apps.settings_page.models import BackupRun

            run = BackupRun.objects.latest("started_at")
            self.assertEqual(run.status, "VERIFIED")
            self.assertFalse(run.offsite)
            self.assertEqual(run.storage, "Encrypted server storage")

    def test_administrator_can_trigger_encrypted_manual_backup(self):
        encryption_key = base64.urlsafe_b64encode(b"x" * 32).decode()
        with tempfile.TemporaryDirectory() as temp_dir, override_settings(
            BACKUP_ROOT=Path(temp_dir),
            FMIS_BACKUP_ENCRYPTION_KEY=encryption_key,
            BACKUP_AZURE_CONTAINER_URL="",
        ):
            self.client.force_login(self.admin)
            response = self.client.post(reverse("settings_page:manual_backup"))
            self.assertRedirects(response, reverse("settings_page:home"))
            self.assertEqual(len(list(Path(temp_dir).glob("fmis-backup-*.fmisbak"))), 1)

            self.client.force_login(self.staff)
            denied = self.client.post(reverse("settings_page:manual_backup"))
            self.assertEqual(denied.status_code, 302)
            self.assertEqual(denied.url, reverse("dashboard:home"))

    def test_backup_screen_is_nontechnical_and_reports_real_configuration(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("settings_page:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Backup &amp; Recovery")
        self.assertContains(response, "Back Up Now")
        self.assertContains(response, "Setup is incomplete")
        self.assertNotContains(response, "JSON")
        self.assertNotContains(response, "downloaded to your device")

    def test_azure_backup_upload_uses_https_and_verifies_remote_size(self):
        from apps.common.backups import _upload_and_verify

        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "fmis-backup-test.fmisbak"
            archive.write_bytes(b"encrypted-backup")
            put_response = Mock(status_code=201)
            head_response = Mock(
                status_code=200,
                headers={"Content-Length": str(archive.stat().st_size)},
            )
            with override_settings(
                BACKUP_AZURE_CONTAINER_URL=(
                    "https://example.blob.core.windows.net/fmis-private?sig=protected"
                )
            ), patch("apps.common.backups.requests.put", return_value=put_response) as upload, patch(
                "apps.common.backups.requests.head", return_value=head_response
            ) as verify:
                self.assertTrue(_upload_and_verify(archive, "a" * 64))
            self.assertTrue(upload.call_args.args[0].startswith("https://"))
            self.assertIn("fmis-backup-test.fmisbak", upload.call_args.args[0])
            self.assertEqual(upload.call_args.kwargs["headers"]["x-ms-blob-type"], "BlockBlob")
            self.assertEqual(verify.call_count, 1)
