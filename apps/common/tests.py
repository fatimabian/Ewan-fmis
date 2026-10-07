import base64
import gzip
import json
import re
import tempfile
import time
from io import BytesIO
from unittest.mock import Mock, patch
from datetime import date
from decimal import Decimal
from pathlib import Path

from django import forms as django_forms
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection
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
from apps.farm_parcels.models import FarmParcel, FarmParcelPhoto
from apps.farmers.forms import (
    CropRegistrationForm,
    CropRegistrationFormSet,
    DocumentRegistrationFormSet,
    FarmerRegistrationForm,
    ParcelRegistrationForm,
    ParcelRegistrationFormSet,
)
from apps.farmers.models import Farmer, FarmerDocument, FarmerUpdateHistory
from apps.interventions.models import Intervention
from apps.reports.export import build_report
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.forms import ServiceRequestForm
from apps.service_requests.models import ServiceRequest, ServiceRequestHistory


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
            valid_id_number="1234567890123456",
            livelihood="FARMER",
            activities="FARMER_CROPS",
            rsbsa_number="RSBSA-001",
            registration_status="COMPLETED",
            consent_given=True,
            remarks="Follow up before seed distribution.",
            created_by=cls.staff,
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
        cls.service, _ = ServiceCatalog.objects.update_or_create(
            code="SEED",
            defaults={
                "name": "Seed Assistance",
                "category": "Farm Inputs",
                "description": "Qualified seed distribution",
                "processing_time": "3 days",
            },
        )

    def test_public_pages_use_the_landing_page_as_the_only_login(self):
        for name in (
            "authentication:landing",
            "authentication:privacy",
            "authentication:terms",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
        self.assertRedirects(
            self.client.get(reverse("authentication:login")),
            reverse("authentication:landing"),
        )
        self.assertContains(
            self.client.get(reverse("authentication:privacy")), "Information collected"
        )
        landing = self.client.get(reverse("authentication:landing"))
        self.assertContains(landing, "rice-field-data-collection.webp")
        self.assertContains(landing, "images/brand/fmis-logo.png")
        self.assertNotContains(landing, 'id="heroCarousel"')
        self.assertNotContains(landing, "data-carousel-next")
        self.assertNotContains(landing, "scope-carousel")
        self.assertContains(landing, "data-service-next")
        self.assertContains(landing, "feature-toggle")
        self.assertContains(landing, "landingProgress")
        self.assertContains(landing, "startServiceCarousel")
        self.assertContains(landing, "advanceServices")

    def test_application_header_shows_only_the_current_page_title(self):
        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse("dashboard:admin_home"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "PENDING ACTIVATIONS")
        self.assertNotContains(admin_response, "Service Catalog")
        self.assertNotContains(admin_response, "Administrator Workspace")
        self.assertEqual(self.client.get("/catalog/").status_code, 404)
        self.assertEqual(self.client.get("/admin/").status_code, 404)

        self.client.force_login(self.staff)
        staff_response = self.client.get(reverse("farmers:list"))
        self.assertEqual(staff_response.status_code, 200)
        self.assertNotContains(staff_response, "Staff Workspace")

    def test_password_fields_have_show_and_hide_controls(self):
        landing = self.client.get(reverse("authentication:landing"))
        self.assertContains(landing, "data-password-toggle", count=1)
        self.assertContains(landing, 'aria-controls="id_password"')
        self.assertContains(landing, "password-toggle.js")

        login_alias = self.client.get(reverse("authentication:login"))
        self.assertRedirects(login_alias, reverse("authentication:landing"))

        self.client.force_login(self.admin)
        account_form = self.client.get(reverse("accounts:create"))
        self.assertEqual(account_form.status_code, 200)
        self.assertContains(account_form, "data-password-toggle", count=2)
        self.assertContains(account_form, 'class="account-password-toggle"', count=2)
        self.assertContains(account_form, 'aria-controls="id_password1"')
        self.assertContains(account_form, 'aria-controls="id_password2"')

    def test_authentication_accepts_valid_credentials_and_rejects_invalid(self):
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
            reverse("authentication:landing"),
            {"username": "staff", "password": "StrongPass123!"},
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
            reverse("authentication:landing"),
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
        session = self.client.session
        self.assertGreaterEqual(session.get_expiry_age(), (7 * 24 * 60 * 60) - 5)
        self.assertIn("fmis_remember_until", session)

    def test_remembered_login_uses_a_fixed_seven_day_limit(self):
        self.client.post(
            reverse("authentication:landing"),
            {
                "username": "staff",
                "password": "StrongPass123!",
                "remember_me": "on",
            },
        )
        session = self.client.session
        session["fmis_last_activity"] = int(time.time()) - (24 * 60 * 60)
        session.save()

        # Remembered users are not incorrectly logged out by the ordinary
        # short idle timeout.
        response = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

        # The remembered login still has a firm security boundary.
        session = self.client.session
        session["fmis_remember_until"] = int(time.time()) - 1
        session.save()
        response = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("authentication:landing")))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unremembered_login_ends_with_the_browser_session(self):
        response = self.client.post(
            reverse("authentication:landing"),
            {"username": "staff", "password": "StrongPass123!"},
        )
        self.assertRedirects(response, reverse("dashboard:staff_home"))
        session = self.client.session
        self.assertTrue(session.get_expire_at_browser_close())
        self.assertNotIn("fmis_remember_until", session)

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

    def test_all_primary_pages_render_for_their_intended_roles(self):
        """Smoke-test every user-facing GET page with realistic linked records."""
        request_record = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Whole-system smoke test request",
            assigned_to=self.staff,
        )
        intervention = Intervention.objects.create(
            farmer=self.farmer,
            service_request=request_record,
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Whole-system smoke test intervention",
            recorded_by=self.staff,
        )

        public_pages = (
            "authentication:landing",
            "authentication:privacy",
            "authentication:terms",
            "authentication:password_reset",
            "authentication:password_reset_done",
            "authentication:password_reset_complete",
        )
        self.client.logout()
        for name in public_pages:
            with self.subTest(role="public", page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

        self.client.force_login(self.admin)
        admin_pages = (
            reverse("dashboard:home"),
            reverse("dashboard:admin_home"),
            reverse("accounts:list"),
            reverse("accounts:create"),
            reverse("accounts:detail", args=[self.staff.pk]),
            reverse("accounts:edit", args=[self.staff.pk]),
            reverse("activity_logs:list"),
            reverse("reports:home"),
            reverse("notifications:list"),
            reverse("settings_page:home"),
        )
        for url in admin_pages:
            with self.subTest(role="admin", page=url):
                self.assertEqual(self.client.get(url, follow=True).status_code, 200)

        self.client.force_login(self.staff)
        staff_pages = (
            reverse("dashboard:home"),
            reverse("dashboard:staff_home"),
            reverse("farmers:list"),
            reverse("farmers:create"),
            reverse("farmers:detail", args=[self.farmer.pk]),
            reverse("farmers:history", args=[self.farmer.pk]),
            reverse("farmers:registration_complete", args=[self.farmer.pk]),
            reverse("farmers:edit", args=[self.farmer.pk]),
            reverse("farmers:registration_status", args=[self.farmer.pk]),
            reverse("farmers:slip_b", args=[self.farmer.pk]),
            reverse("farmers:qr_print", args=[self.farmer.pk]),
            reverse("farm_parcels:list"),
            reverse("farm_parcels:map"),
            reverse("farm_parcels:create"),
            reverse("farm_parcels:detail", args=[self.parcel.pk]),
            reverse("farm_parcels:history", args=[self.parcel.pk]),
            reverse("farm_parcels:edit", args=[self.parcel.pk]),
            reverse("crops:list"),
            reverse("crops:create"),
            reverse("crops:detail", args=[self.crop.pk]),
            reverse("crops:history", args=[self.crop.pk]),
            reverse("crops:edit", args=[self.crop.pk]),
            reverse("service_requests:list"),
            reverse("service_requests:create"),
            reverse("service_requests:detail", args=[request_record.pk]),
            reverse("service_requests:history", args=[request_record.pk]),
            reverse("service_requests:edit", args=[request_record.pk]),
            reverse("interventions:list"),
            reverse("interventions:create"),
            reverse("interventions:detail", args=[intervention.pk]),
            reverse("interventions:history", args=[intervention.pk]),
            reverse("interventions:edit", args=[intervention.pk]),
            reverse("reports:home"),
            reverse("notifications:list"),
            reverse("settings_page:home"),
        )
        for url in staff_pages:
            with self.subTest(role="staff", page=url):
                self.assertEqual(self.client.get(url, follow=True).status_code, 200)

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

        landing = self.client.get(response.url)
        timeout_message = "Your session expired due to inactivity. Please sign in again."
        self.assertContains(landing, timeout_message)
        login_response = self.client.post(
            reverse("authentication:landing"),
            {"username": "staff", "password": "StrongPass123!"},
        )
        self.assertRedirects(login_response, reverse("dashboard:staff_home"))
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertNotContains(dashboard, timeout_message)

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
                "valid_id_number": "1234567890123456",
                "livelihood": "FARMER",
                "activities": "FARMER_CROPS",
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

    def test_service_requests_use_protected_standard_dropdown(self):
        self.assertTrue(ServiceCatalog.objects.filter(code="OTHER", is_active=True).exists())
        self.assertGreaterEqual(ServiceCatalog.objects.filter(is_active=True).count(), 23)
        legacy = ServiceCatalog.objects.create(
            code="LEGACY-QA",
            name="Legacy Sample Service",
            category="Other",
            description="Legacy sample entry",
            processing_time="Not applicable",
            is_active=True,
        )
        form = ServiceRequestForm()
        self.assertIsInstance(form.fields["service"].widget, django_forms.Select)
        self.assertNotIn(legacy.pk, form.fields["service"].queryset.values_list("pk", flat=True))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("service_requests:create"))
        self.assertContains(response, "Other Agricultural Concern")
        self.assertContains(response, "Select an agricultural request type")
        self.assertNotContains(response, "Legacy Sample Service")

    def test_farmer_type_is_a_single_dropdown(self):
        form = FarmerRegistrationForm()
        self.assertIsInstance(form.fields["livelihood"].widget, django_forms.Select)
        self.assertNotIn("activities", form.fields)
        self.assertEqual(
            [value for value, _label in form.fields["livelihood"].choices if value],
            [value for value, _label in Farmer.LIVELIHOOD_CHOICES],
        )

    def test_valid_id_format_depends_on_selected_id_type(self):
        base_data = {
            "last_name": "Ramirez",
            "first_name": "Fatima",
            "sex": "FEMALE",
            "birth_date": "1990-01-02",
            "place_of_birth": "Rosario",
            "mother_maiden_name": "Perea",
            "barangay": "Bagong Pook",
            "phone_number": "09953092018",
            "civil_status": "SINGLE",
            "livelihood": "FARMER",
            "consent_given": "on",
        }
        short_national_id = FarmerRegistrationForm(
            data={**base_data, "valid_id_type": "National ID", "valid_id_number": "1234"}
        )
        self.assertFalse(short_national_id.is_valid())
        self.assertIn("16-digit", short_national_id.errors["valid_id_number"][0])

        driver_id = FarmerRegistrationForm(
            data={
                **base_data,
                "valid_id_type": "Driver's License",
                "valid_id_number": "N01-12-123456",
            }
        )
        driver_id.is_valid()
        self.assertNotIn("valid_id_number", driver_id.errors)

    def test_birth_date_rejects_future_and_farmers_ten_or_younger(self):
        today = date.today()
        try:
            tenth_birthday = today.replace(year=today.year - 10)
            eleventh_birthday = today.replace(year=today.year - 11)
        except ValueError:
            tenth_birthday = date(today.year - 10, 2, 28)
            eleventh_birthday = date(today.year - 11, 2, 28)

        base_data = {
            "last_name": "Ramirez",
            "first_name": "Fatima",
            "sex": "FEMALE",
            "place_of_birth": "Rosario",
            "mother_maiden_name": "Perea",
            "barangay": "Bagong Pook",
            "phone_number": "09953092018",
            "civil_status": "SINGLE",
            "valid_id_type": "Driver's License",
            "valid_id_number": "N01-12-654321",
            "livelihood": "FARMER",
            "is_indigenous": "NA",
            "is_pwd": "NA",
            "is_four_ps": "NA",
            "consent_given": "on",
        }

        future_form = FarmerRegistrationForm(
            data={**base_data, "birth_date": date(today.year + 1, 1, 1).isoformat()}
        )
        self.assertFalse(future_form.is_valid())
        self.assertIn("future date", future_form.errors["birth_date"][0])

        ten_year_old_form = FarmerRegistrationForm(
            data={**base_data, "birth_date": tenth_birthday.isoformat()}
        )
        self.assertFalse(ten_year_old_form.is_valid())
        self.assertIn("at least 11", ten_year_old_form.errors["birth_date"][0])

        eleven_year_old_form = FarmerRegistrationForm(
            data={**base_data, "birth_date": eleventh_birthday.isoformat()}
        )
        eleven_year_old_form.is_valid()
        self.assertNotIn("birth_date", eleven_year_old_form.errors)
        self.assertEqual(
            FarmerRegistrationForm().fields["birth_date"].widget.attrs["max"],
            eleventh_birthday.isoformat(),
        )

    def test_special_classifications_use_clear_yes_no_choices(self):
        form = FarmerRegistrationForm(
            data={
                "last_name": "Ramirez",
                "first_name": "Fatima",
                "sex": "FEMALE",
                "birth_date": "1990-01-02",
                "place_of_birth": "Rosario",
                "mother_maiden_name": "Perea",
                "barangay": "Bagong Pook",
                "phone_number": "09953092018",
                "civil_status": "SINGLE",
                "valid_id_type": "National ID",
                "valid_id_number": "8888777766665555",
                "livelihood": "FARMER",
                "is_indigenous": "False",
                "is_pwd": "False",
                "is_four_ps": "False",
                "consent_given": "on",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        for name in ("is_indigenous", "is_pwd", "is_four_ps"):
            self.assertNotIn(("NA", "N/A / Not applicable"), form.fields[name].choices)
            self.assertFalse(form.cleaned_data[name])
        self.assertNotIn("N/A / Not applicable", dict(form.fields["philsys_registered"].choices).values())

        missing_choices = FarmerRegistrationForm(data={})
        missing_choices.is_valid()
        for name in ("is_indigenous", "is_pwd", "is_four_ps"):
            self.assertIn(name, missing_choices.errors)

    def test_invalid_registration_explains_that_nothing_was_saved(self):
        self.client.force_login(self.staff)
        farmer_count = Farmer.objects.count()
        response = self.client.post(reverse("farmers:create"), {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registration was not saved.")
        self.assertContains(response, "No partial farmer record was created.")
        self.assertEqual(Farmer.objects.count(), farmer_count)

    def _valid_registration_payload(self):
        return {
            "last_name": "Dela Cruz",
            "first_name": "Maria",
            "sex": "FEMALE",
            "birth_date": "1992-04-08",
            "place_of_birth": "Rosario",
            "mother_maiden_name": "Santos",
            "barangay": "Alupay",
            "phone_number": "09181234567",
            "civil_status": "SINGLE",
            "valid_id_type": "National ID",
            "valid_id_number": "9999888877776666",
            "livelihood": "FARMER",
            "is_indigenous": "NA",
            "is_pwd": "False",
            "is_four_ps": "NA",
            "consent_given": "on",
            "parcels-TOTAL_FORMS": "1",
            "parcels-INITIAL_FORMS": "0",
            "parcels-MIN_NUM_FORMS": "1",
            "parcels-MAX_NUM_FORMS": "1000",
            "parcels-0-barangay": "Alupay",
            "parcels-0-area_hectares": "1.50",
            "parcels-0-ownership_type": "OWNED",
            "parcels-0-land_type": "UPLAND",
            "parcels-0-farm_type": "Mixed vegetables",
            "parcels-0-is_active": "True",
            "crops-TOTAL_FORMS": "1",
            "crops-INITIAL_FORMS": "0",
            "crops-MIN_NUM_FORMS": "1",
            "crops-MAX_NUM_FORMS": "1000",
            "crops-0-parcel_number": "1",
            "crops-0-crop_type": "Rice",
            "crops-0-cropping_start_month": "January",
            "crops-0-cropping_end_month": "March",
            "crops-0-area_hectares": "1.00",
            "crops-0-is_organic": "False",
            "crops-0-is_intercrop": "False",
            "documents-TOTAL_FORMS": "1",
            "documents-INITIAL_FORMS": "0",
            "documents-MIN_NUM_FORMS": "1",
            "documents-MAX_NUM_FORMS": "1000",
            "documents-0-document_type": "VALID_ID",
            "documents-0-description": "National ID",
            "documents-0-file": SimpleUploadedFile(
                "valid-id.pdf",
                b"%PDF-1.4\nFMIS test document\n%%EOF",
                content_type="application/pdf",
            ),
        }

    def test_registration_saves_all_sections_as_one_transaction(self):
        self.client.force_login(self.staff)
        farmer_count = Farmer.objects.count()
        response = self.client.post(
            reverse("farmers:create"),
            self._valid_registration_payload(),
        )
        self.assertEqual(response.status_code, 302, response.context)
        self.assertEqual(Farmer.objects.count(), farmer_count + 1)
        saved = Farmer.objects.get(valid_id_number="9999888877776666")
        self.assertFalse(saved.is_indigenous)
        self.assertFalse(saved.is_pwd)
        self.assertFalse(saved.is_four_ps)
        self.assertEqual(saved.parcels.count(), 1)
        self.assertEqual(saved.parcels.get().crops.count(), 1)
        self.assertEqual(saved.documents.count(), 1)

    def test_registration_accepts_other_supporting_document_without_valid_id(self):
        self.client.force_login(self.staff)
        payload = self._valid_registration_payload()
        payload["valid_id_type"] = ""
        payload["valid_id_number"] = ""
        payload["documents-0-document_type"] = "OWNERSHIP"
        payload["documents-0-description"] = "Barangay-certified tenure record"

        response = self.client.post(reverse("farmers:create"), payload)

        self.assertEqual(response.status_code, 302, response.context)
        saved = Farmer.objects.get(first_name="Maria", last_name="Dela Cruz")
        self.assertEqual(saved.valid_id_type, "")
        self.assertEqual(saved.valid_id_number, "")
        self.assertEqual(saved.documents.get().document_type, "OWNERSHIP")

    def test_database_save_failure_rolls_back_and_shows_retry_message(self):
        self.client.force_login(self.staff)
        farmer_count = Farmer.objects.count()
        with patch("apps.farmers.views.Farmer.save", side_effect=DatabaseError("offline")):
            response = self.client.post(
                reverse("farmers:create"),
                self._valid_registration_payload(),
            )
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "temporarily unavailable", status_code=503)
        self.assertContains(response, "No partial record was created", status_code=503)
        self.assertEqual(Farmer.objects.count(), farmer_count)

    def test_land_owner_fields_are_conditional_on_ownership(self):
        base_data = {
            "barangay": "Alupay",
            "area_hectares": "1.50",
            "land_type": "UPLAND",
            "farm_type": "Mixed vegetables near the creek",
            "is_active": "True",
        }
        owned = ParcelRegistrationForm(data={**base_data, "ownership_type": "OWNED"})
        self.assertTrue(owned.is_valid(), owned.errors)

        tenant_without_owner = ParcelRegistrationForm(
            data={**base_data, "ownership_type": "TENANT"}
        )
        self.assertFalse(tenant_without_owner.is_valid())
        self.assertIn("land_owner_name", tenant_without_owner.errors)

        tenant_with_registered_owner = ParcelRegistrationForm(
            data={
                **base_data,
                "ownership_type": "TENANT",
                "land_owner_name": "Juan Dela Cruz",
                "land_owner_registered_rsbsa": "True",
                "land_owner_rsbsa_number": "RSBSA-OWNER-001",
            }
        )
        self.assertTrue(tenant_with_registered_owner.is_valid(), tenant_with_registered_owner.errors)

    def test_cropping_month_dropdowns_build_the_saved_schedule(self):
        crop_form = CropRegistrationForm(
            data={
                "parcel_number": "1",
                "crop_type": "Rice",
                "cropping_start_month": "January",
                "cropping_end_month": "March",
                "area_hectares": "0.75",
                "is_organic": "False",
                "is_intercrop": "False",
            }
        )
        self.assertTrue(crop_form.is_valid(), crop_form.errors)
        self.assertEqual(crop_form.cleaned_data["cropping_schedule"], "January - March")

    def test_farmer_registration_rejects_wrong_character_types(self):
        form = FarmerRegistrationForm(
            data={
                "last_name": "Sant0s",
                "first_name": "An4",
                "sex": "FEMALE",
                "birth_date": "1980-01-02",
                "place_of_birth": "Rosario",
                "mother_maiden_name": "Reyes",
                "house_lot_purok": "Purok 2",
                "barangay": "Bulihan",
                "city_municipality": "Rosario",
                "province": "Batangas",
                "region": "CALABARZON Region IV-A",
                "phone_number": "0917ABC4567",
                "civil_status": "SINGLE",
                "valid_id_type": "National ID",
                "valid_id_number": "<script>",
                "livelihood": "FARMER",
                "activities": "FARMER_CROPS",
                "consent_given": "on",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("letters only", form.errors["last_name"][0].lower())
        self.assertIn("letters only", form.errors["first_name"][0].lower())
        self.assertIn("numbers only", form.errors["phone_number"][0].lower())
        self.assertIn("16-digit", form.errors["valid_id_number"][0].lower())

        blank_form = FarmerRegistrationForm()
        self.assertEqual(blank_form.fields["first_name"].widget.attrs["data-input-kind"], "letters")
        self.assertEqual(blank_form.fields["phone_number"].widget.attrs["data-input-kind"], "digits")
        self.assertIsInstance(blank_form.fields["valid_id_type"].widget, django_forms.Select)
        self.assertEqual(blank_form.fields["valid_id_number"].widget.attrs["data-valid-id-number"], "true")

    def test_farmer_registration_workflow_is_managed_separately_from_slip_a(self):
        self.client.force_login(self.staff)

        masterlist = self.client.get(reverse("farmers:list"))
        self.assertEqual(masterlist.status_code, 200)
        self.assertContains(masterlist, "Farmer ID")
        self.assertContains(masterlist, "<th>RSBSA ID</th>", html=True)
        self.assertContains(masterlist, "<th>Status</th>", html=True)
        self.assertNotContains(masterlist, 'name="registration_status"')
        self.assertNotContains(masterlist, "farmer-workflow-input")

        create_page = self.client.get(reverse("farmers:create"))
        self.assertContains(create_page, "<strong>Encoded</strong>", html=True)

        edit_page = self.client.get(reverse("farmers:edit", args=[self.farmer.pk]))
        self.assertEqual(edit_page.status_code, 200)
        self.assertNotContains(edit_page, 'name="registration_status"')
        self.assertNotContains(edit_page, 'name="rsbsa_number"')

        status_page = self.client.get(
            reverse("farmers:registration_status", args=[self.farmer.pk])
        )
        self.assertEqual(status_page.status_code, 200)
        self.assertContains(status_page, 'name="registration_status"')
        self.assertContains(status_page, 'name="rsbsa_number"')
        self.assertNotContains(status_page, 'name="transaction_code"')
        self.assertNotContains(status_page, 'name="registrant_declaration"')

        detail_page = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
        self.assertContains(detail_page, "status-action-completed")
        self.assertNotContains(detail_page, 'class="farmer-status status-completed"')

    def test_office_status_update_needs_no_slip_a_transaction(self):
        self.client.force_login(self.staff)
        self.farmer.registration_status = "ENCODED"
        self.farmer.rsbsa_number = None
        self.farmer.save(update_fields=["registration_status", "rsbsa_number"])

        response = self.client.post(
            reverse("farmers:registration_status", args=[self.farmer.pk]),
            {"registration_status": "SUBMITTED", "rsbsa_number": ""},
        )
        self.assertRedirects(response, reverse("farmers:detail", args=[self.farmer.pk]))
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.registration_status, "SUBMITTED")
        history = FarmerUpdateHistory.objects.get(farmer=self.farmer, update_type="STATUS")
        self.assertEqual(history.actor, self.staff)
        self.assertEqual(history.transaction_code, "")
        self.assertTrue(
            any(change["field"] == "Personal / Registration Status" for change in history.changes)
        )

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

    def test_record_details_are_separated_by_management_context(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
        self.assertContains(response, "Follow up before seed distribution")
        self.assertContains(response, "Personal Information")
        self.assertNotContains(response, "Farm Parcels")
        self.assertNotContains(response, '<h3><i class="bi bi-headset"></i> Service Requests</h3>')
        parcel_response = self.client.get(reverse("farm_parcels:detail", args=[self.parcel.pk]))
        self.assertContains(parcel_response, "Parcel Information")
        self.assertNotContains(parcel_response, "Registered Farmer")
        self.assertNotContains(parcel_response, "Crops on This Parcel")
        crop_response = self.client.get(reverse("crops:detail", args=[self.crop.pk]))
        self.assertContains(crop_response, "Crop &amp; Production Information")
        self.assertNotContains(crop_response, "Registered Farmer")
        self.assertNotContains(crop_response, '<h3><i class="bi bi-map"></i> Farm Parcel</h3>')

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
                "valid_id_number": "1234567890123456",
                "religion": "",
                "indigenous_group": "",
                "fca_membership": "",
                "remarks": "Follow up before seed distribution.",
                "location_coordinates": "",
                "registration_status": "COMPLETED",
                "rsbsa_number": "RSBSA-001",
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
        self.assertEqual(
            response.url,
            f'{reverse("farmers:detail", args=[self.farmer.pk])}?saved=slip-a',
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
        self.assertContains(detail, reverse("farmers:history", args=[self.farmer.pk]))
        self.assertNotContains(detail, "SLIP-A-001")
        saved_detail = self.client.get(
            f'{reverse("farmers:detail", args=[self.farmer.pk])}?saved=slip-a'
        )
        self.assertContains(saved_detail, "Slip A update saved.")
        self.assertContains(saved_detail, "now recorded in Update History")
        history_page = self.client.get(reverse("farmers:history", args=[self.farmer.pk]))
        self.assertEqual(history_page.status_code, 200)
        self.assertContains(history_page, "Farmer Information Update History")
        self.assertContains(history_page, "Record created")
        self.assertContains(history_page, "Farmer name")
        self.assertContains(history_page, "Date created")
        self.assertContains(history_page, self.staff.display_name)
        self.assertContains(history_page, "SLIP-A-001")
        self.assertContains(history_page, self.staff.display_name)
        self.assertContains(history_page, "Edited by")
        self.assertContains(history_page, "Account")
        self.assertContains(history_page, f"@{self.staff.username}")
        self.assertContains(history_page, "Date")
        self.assertContains(history_page, "Time")
        self.assertContains(history_page, "Transaction code: SLIP-A-001")
        self.assertContains(history_page, "Update status: Completed")
        self.assertEqual(history_page.context["history_entries"][0]["transaction_code"], "SLIP-A-001")
        farmer_list = self.client.get(reverse("farmers:list"))
        self.assertNotContains(farmer_list, "Last Updated By")
        self.assertNotContains(farmer_list, "Latest Change")
        self.assertNotContains(farmer_list, "farmer-update-details")
        self.assertNotContains(farmer_list, "View update details")
        self.assertNotContains(farmer_list, "Personal / Phone Number")

    def test_management_records_use_dedicated_history_pages(self):
        self.client.force_login(self.staff)
        request_record = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Seed request",
        )
        ServiceRequestHistory.objects.create(
            service_request=request_record,
            actor=self.staff,
            action="CREATED",
            to_status="PENDING",
        )
        intervention = Intervention.objects.create(
            farmer=self.farmer,
            service_request=request_record,
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Certified rice seed distribution",
            recorded_by=self.staff,
        )

        records = (
            ("farmers", self.farmer.pk, "Farmer Information Update History"),
            ("farm_parcels", self.parcel.pk, "Farm Parcel Update History"),
            ("crops", self.crop.pk, "Crop Record Update History"),
            ("service_requests", request_record.pk, "Service Request History"),
            ("interventions", intervention.pk, "Intervention Update History"),
        )
        for namespace, pk, title in records:
            with self.subTest(namespace=namespace):
                detail = self.client.get(reverse(f"{namespace}:detail", args=[pk]))
                history_url = reverse(f"{namespace}:history", args=[pk])
                self.assertEqual(detail.status_code, 200)
                self.assertContains(detail, history_url)
                history_page = self.client.get(history_url)
                self.assertEqual(history_page.status_code, 200)
                self.assertContains(history_page, title)

        service_history_page = self.client.get(
            reverse("service_requests:history", args=[request_record.pk])
        )
        self.assertContains(service_history_page, "Edited by")
        self.assertContains(service_history_page, self.staff.display_name)
        self.assertContains(service_history_page, f"@{self.staff.username}")
        self.assertContains(service_history_page, "Staff")
        self.assertContains(service_history_page, "Date")
        self.assertContains(service_history_page, "Time")
        self.assertContains(service_history_page, "SRH-")

        service_detail = self.client.get(
            reverse("service_requests:detail", args=[request_record.pk])
        )
        self.assertNotContains(service_detail, 'class="request-history"')
        self.assertNotContains(service_detail, "Delivered Interventions")
        self.assertNotContains(service_detail, intervention.reference_id)
        request_record.status = "IN_PROGRESS"
        request_record.save(update_fields=["status"])
        linked_form = self.client.get(
            reverse("interventions:create"),
            {"service_request": request_record.pk},
        )
        self.assertEqual(linked_form.status_code, 200)
        self.assertEqual(
            linked_form.context["form"].initial["service_request"], request_record
        )
        self.assertEqual(linked_form.context["form"].initial["farmer"], self.farmer)

    def test_single_farmer_rsbsa_export_includes_official_form_and_complete_record(self):
        from pypdf import PdfReader

        self.client.force_login(self.staff)
        service_request = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Request certified seed assistance",
            priority="MEDIUM",
            status="COMPLETED",
            assigned_to=self.staff,
        )
        intervention = Intervention.objects.create(
            farmer=self.farmer,
            service_request=service_request,
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Certified seed assistance issued",
            quantity=Decimal("2.00"),
            unit="bags",
            estimated_value=Decimal("3200.00"),
            recorded_by=self.staff,
        )
        farmer_detail = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
        export_url = reverse("farmers:rsbsa_export", args=[self.farmer.pk])
        self.assertContains(farmer_detail, export_url)

        response = self.client.get(export_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        reader = PdfReader(BytesIO(response.content))
        self.assertGreaterEqual(len(reader.pages), 3)
        self.assertEqual(reader.metadata.title, f"RSBSA Enrollment Form - {self.farmer.full_name}")
        exported_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        exported_compact = "".join(exported_text.split())
        self.assertIn("FMIS CURRENT FARMER RECORD", exported_text)
        self.assertIn("Personal and Registration Information", exported_text)
        self.assertIn("Farm Parcels", exported_text)
        self.assertIn("Supporting Documents", exported_text)
        self.assertIn("Service Requests", exported_text)
        self.assertIn("Interventions Given", exported_text)
        self.assertIn(service_request.request_id, exported_text)
        self.assertIn(intervention.reference_id, exported_text)
        for expected in (
            self.farmer.first_name.upper(),
            self.farmer.last_name.upper(),
            self.farmer.barangay.upper(),
            self.farmer.rsbsa_number,
            self.parcel.barangay.upper(),
            self.crop.crop_type.upper(),
        ):
            self.assertIn(expected, exported_text)
        # The official template supplies the leading "09" as static artwork;
        # the PDF overlay contributes the remaining digits box by box.
        phone_tail = self.farmer.phone_number[2:] if self.farmer.phone_number.startswith("09") else self.farmer.phone_number
        self.assertIn(phone_tail, exported_compact)

    def test_in_progress_service_request_proceeds_to_intervention_and_completes(self):
        self.client.force_login(self.staff)
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Distribute certified rice seed",
            priority="MEDIUM",
            status="IN_PROGRESS",
            notes="Two bags approved for release.",
            assigned_to=self.staff,
        )
        update_url = reverse("service_requests:edit", args=[request_item.pk])
        payload = {
            "farmer": self.farmer.pk,
            "service": self.service.pk,
            "subject": request_item.subject,
            "priority": "MEDIUM",
            "status": "IN_PROGRESS",
            "notes": request_item.notes,
            "assigned_to": self.staff.pk,
        }
        response = self.client.post(update_url, payload)
        self.assertRedirects(response, reverse("service_requests:list"))
        self.assertFalse(Intervention.objects.filter(service_request=request_item).exists())
        response = self.client.post(
            f"{reverse('interventions:create')}?service_request={request_item.pk}",
            {
                "farmer": self.farmer.pk,
                "service_request": request_item.pk,
                "intervention_type": "SEEDS",
                "intervention_date": date.today().isoformat(),
                "description": "Certified rice seed delivered",
                "quantity": "2",
                "unit": "bags",
                "provider": "Office for Agricultural Services",
                "remarks": request_item.notes,
            },
        )
        self.assertRedirects(response, reverse("interventions:list"))
        intervention = Intervention.objects.get(service_request=request_item)
        self.assertEqual(intervention.farmer, self.farmer)
        self.assertEqual(intervention.intervention_type, "SEEDS")
        self.assertEqual(intervention.recorded_by, self.staff)
        request_item.refresh_from_db()
        self.assertEqual(request_item.status, "COMPLETED")

        default_list = self.client.get(reverse("service_requests:list"))
        self.assertNotContains(default_list, request_item.request_id)
        self.assertNotContains(default_list, "Record intervention for")
        completed_list = self.client.get(
            reverse("service_requests:list"),
            {"status": "COMPLETED"},
        )
        self.assertContains(completed_list, request_item.request_id)

        blocked = self.client.get(
            reverse("interventions:create"),
            {"service_request": request_item.pk},
        )
        self.assertRedirects(blocked, reverse("service_requests:detail", args=[request_item.pk]))

    def test_slip_b_is_separate_and_contains_official_parcel_workflow(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:slip_b", args=[self.farmer.pk]))
        self.assertRedirects(
            response,
            reverse("farm_parcels:edit", args=[self.parcel.pk]),
        )
        parcel_form = self.client.get(reverse("farm_parcels:edit", args=[self.parcel.pk]))
        self.assertContains(parcel_form, "Update Slip B")
        self.assertContains(parcel_form, "Slip B is for verified parcel and land changes")
        self.assertNotContains(parcel_form, "Crops and Commodities")
        self.assertNotContains(parcel_form, 'name="field_photos"')
        for field_name in (
            "gpx_status",
            "rotational_tiller",
            "land_owner_rsbsa_number",
            "ownership_document_other",
        ):
            self.assertContains(parcel_form, field_name)

        saved_detail = self.client.get(
            f'{reverse("farm_parcels:detail", args=[self.parcel.pk])}?saved=slip-b'
        )
        self.assertContains(saved_detail, "Slip B update saved.")
        self.assertContains(saved_detail, "now recorded in Update History")

        FarmerUpdateHistory.objects.create(
            farmer=self.farmer,
            actor=self.staff,
            update_type="SLIP_B",
            transaction_code="SLIP-B-001",
            changes=[
                {
                    "field": "Parcel 1 / Area Hectares",
                    "before": "1.00",
                    "after": "2.00",
                }
            ],
        )
        history_page = self.client.get(reverse("farm_parcels:history", args=[self.parcel.pk]))
        self.assertContains(history_page, "Slip B - Farm Parcel Update History")
        self.assertContains(history_page, "Transaction code: SLIP-B-001")
        self.assertContains(history_page, "Update status: Completed")
        self.assertEqual(
            history_page.context["history_entries"][0]["transaction_code"],
            "SLIP-B-001",
        )
        farmer_history = self.client.get(reverse("farmers:history", args=[self.farmer.pk]))
        self.assertNotContains(farmer_history, "SLIP-B-001")
        self.assertNotContains(farmer_history, "Slip B - Farm Parcel Information")

    def test_office_uploads_field_photos_from_parcel_gallery_not_slip_b(self):
        from PIL import Image

        self.client.force_login(self.staff)
        parcel_detail = self.client.get(reverse("farm_parcels:detail", args=[self.parcel.pk]))
        self.assertContains(parcel_detail, "Office field documentation")
        self.assertContains(parcel_detail, 'name="field_photos"')

        image_bytes = BytesIO()
        Image.new("RGB", (16, 16), "green").save(image_bytes, format="PNG")
        history_count = FarmerUpdateHistory.objects.filter(
            farmer=self.farmer, update_type="SLIP_B"
        ).count()
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("farm_parcels:photo_upload", args=[self.parcel.pk]),
                {
                    "field_photos": SimpleUploadedFile(
                        "field.png", image_bytes.getvalue(), content_type="image/png"
                    )
                },
            )
            self.assertRedirects(response, reverse("farm_parcels:detail", args=[self.parcel.pk]))
            photo = FarmParcelPhoto.objects.get(parcel=self.parcel)
            self.assertEqual(photo.uploaded_by, self.staff)
            self.assertTrue(photo.is_active)
        self.assertEqual(
            FarmerUpdateHistory.objects.filter(
                farmer=self.farmer, update_type="SLIP_B"
            ).count(),
            history_count,
        )
        self.assertTrue(
            ActivityLog.objects.filter(title="Farm Parcel Photos Added").exists()
        )

    def test_cancelled_service_request_is_locked_and_cannot_start_intervention(self):
        self.client.force_login(self.staff)
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Cancelled seed request",
            status="CANCELLED",
        )
        edit_response = self.client.get(
            reverse("service_requests:edit", args=[request_item.pk])
        )
        self.assertRedirects(
            edit_response,
            reverse("service_requests:detail", args=[request_item.pk]),
        )
        detail = self.client.get(reverse("service_requests:detail", args=[request_item.pk]))
        self.assertNotContains(detail, "Update Service Request")
        intervention = self.client.get(
            reverse("interventions:create"), {"service_request": request_item.pk}
        )
        self.assertRedirects(
            intervention,
            reverse("service_requests:detail", args=[request_item.pk]),
        )

    def test_parcel_table_hides_rsbsa_column_and_map_can_focus_saved_parcel(self):
        self.client.force_login(self.staff)
        parcel_list = self.client.get(reverse("farm_parcels:list"))
        self.assertEqual(parcel_list.status_code, 200)
        self.assertNotContains(parcel_list, "RSBSA Record")
        self.assertNotContains(parcel_list, '<select name="crop_type"', html=False)
        self.assertNotContains(parcel_list, "<th>Crop</th>", html=False)

        self.parcel.coordinates = "13.8467000, 121.2060000"
        self.parcel.save(update_fields=["coordinates"])
        map_response = self.client.get(reverse("farm_parcels:map"))
        self.assertEqual(map_response.status_code, 200)
        self.assertEqual(map_response.context["mapped_count"], 1)
        self.assertEqual(map_response.context["map_markers"][0]["id"], self.parcel.pk)
        self.assertContains(map_response, "markerByFarmer")
        self.assertContains(map_response, "Parcel Already Pinned")
        self.assertContains(map_response, "farmerMarker.openPopup()")
        self.assertContains(map_response, "Satellite")
        self.assertContains(map_response, "Terrain")
        self.assertContains(map_response, "maxBounds: rosarioBounds")

    def test_parcel_map_rejects_pins_outside_rosario_batangas(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("farm_parcels:pin_farmer"),
            {
                "parcel_id": self.parcel.pk,
                "latitude": "14.5995",
                "longitude": "120.9842",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("outside Rosario", response.json()["message"])
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.coordinates, "")

    def test_staff_can_move_parcel_pin_and_change_is_audited(self):
        self.parcel.coordinates = "13.8467000, 121.2060000"
        self.parcel.save(update_fields=["coordinates"])
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("farm_parcels:pin_farmer"),
            {
                "parcel_id": self.parcel.pk,
                "latitude": "13.8501000",
                "longitude": "121.2102000",
                "operation": "move",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.coordinates, "13.8501000, 121.2102000")
        activity = ActivityLog.objects.get(
            title="Farm Parcel Map Pin Moved",
            target_label=f"{self.farmer.record_id} - {self.parcel.display_name}",
        )
        self.assertEqual(activity.actor, self.staff)
        self.assertEqual(activity.details[0]["before"], "13.8467000, 121.2060000")
        self.assertEqual(activity.details[0]["after"], "13.8501000, 121.2102000")

        map_response = self.client.get(reverse("farm_parcels:map"))
        self.assertContains(map_response, "Right-click a green parcel pin to move it")
        self.assertContains(map_response, "Save New Location")

    def test_parcel_form_is_land_only_and_crops_are_managed_separately(self):
        self.client.force_login(self.staff)
        create_url = reverse("farm_parcels:create")
        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("crop_formset", response.context)
        self.assertNotContains(response, "Add Crop")
        self.assertContains(response, "Add commodities separately in Crop Management")

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
        }
        valid = self.client.post(create_url, base_data)
        self.assertEqual(valid.status_code, 302)
        created_parcel = FarmParcel.objects.exclude(pk=self.parcel.pk).get()
        self.assertFalse(created_parcel.crops.exists())

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
            "RSBSA ID",
            "Status",
            "Actions",
        ):
            self.assertContains(response, f"<th>{heading}</th>", html=True)
        self.assertNotContains(response, "<th>Last Updated By</th>", html=True)
        self.assertNotContains(response, "<th>Age</th>", html=True)
        self.assertNotContains(response, "<th>Sex</th>", html=True)
        self.assertContains(response, self.farmer.record_id)
        self.assertContains(response, self.farmer.list_name)
        self.assertContains(response, self.farmer.phone_number)
        self.assertContains(response, self.farmer.get_livelihood_display())
        self.assertContains(response, self.farmer.rsbsa_number)
        self.assertContains(response, self.farmer.get_registration_status_display())
        self.assertContains(response, 'class="farmer-status status-completed"')

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
        parcel_fields = response.context["parcel_formset"].empty_form.fields
        self.assertIsInstance(parcel_fields["farm_type"].widget, django_forms.TextInput)
        self.assertNotIn("parcel_name", parcel_fields)
        self.assertNotIn("remarks", parcel_fields)
        self.assertNotIn("is_rsbsa_recorded", parcel_fields)
        crop_fields = response.context["crop_formset"].empty_form.fields
        self.assertNotIn("is_active", crop_fields)
        self.assertNotIn("archived_at", crop_fields)
        self.assertNotIn("archived_by", crop_fields)

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
                "crops-0-cropping_start_month": "January",
                "crops-0-cropping_end_month": "March",
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

    def test_intervention_summary_and_complete_register_reports(self):
        service_request = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Certified rice seed request",
            status="COMPLETED",
        )
        intervention = Intervention.objects.create(
            farmer=self.farmer,
            service_request=service_request,
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Certified rice seed distribution",
            quantity=Decimal("2.00"),
            unit="bags",
            estimated_value=Decimal("3200.00"),
            funding_source="Municipal Agriculture Office",
            recorded_by=self.staff,
        )
        title, headers, rows = build_report("intervention_summary", "all", {})
        self.assertEqual(title, "Intervention Distribution Summary")
        self.assertIn("Farmers Served", headers)
        self.assertEqual(rows[0][1:], [1, 1])

        title, headers, rows = build_report("intervention_registry", "all", {})
        self.assertEqual(title, "Complete Intervention Register")
        self.assertIn("Recorded By", headers)
        self.assertEqual(rows[0][0], intervention.reference_id)
        self.assertEqual(rows[0][3], self.farmer.full_name)
        self.assertEqual(rows[0][7], "2.00 bags")
        self.assertNotIn("Estimated Value (PHP)", headers)
        self.assertNotIn("Funding Source", headers)
        self.assertEqual(rows[0][9], service_request.request_id)

        self.client.force_login(self.staff)
        reports = self.client.get(
            reverse("reports:home"),
            {"report_type": "intervention_registry", "date_range": "all"},
        )
        self.assertContains(reports, "Complete Intervention Register")
        self.assertContains(reports, intervention.reference_id)
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertContains(dashboard, "Interventions Given")
        self.assertNotContains(dashboard, "Open Service Requests")

    def test_service_request_report_lists_who_where_when_and_what(self):
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Request certified rice seed",
            status="PENDING",
            priority="HIGH",
            assigned_to=self.staff,
        )
        title, headers, rows = build_report("service_status", "all", {"status": "PENDING"})
        self.assertEqual(title, "Service Request Status")
        for header in ("Farmer", "Barangay", "Request Type", "Request", "Date Requested"):
            self.assertIn(header, headers)
        row = next(item for item in rows if item[0] == request_item.request_id)
        self.assertEqual(row[2], self.farmer.full_name)
        self.assertEqual(row[3], self.farmer.barangay)
        self.assertEqual(row[5], request_item.subject)

    def test_farmer_master_list_orders_generated_ids_chronologically(self):
        Farmer.objects.create(
            first_name="Zena",
            last_name="Alpha",
            sex="FEMALE",
            birth_date=date(1985, 1, 1),
            place_of_birth="Rosario",
            mother_maiden_name="Reyes",
            house_lot_purok="Purok 2",
            barangay="Bulihan",
            phone_number="09170000001",
            civil_status="SINGLE",
            valid_id_type="National ID",
            valid_id_number="1111222233334444",
            livelihood="FARMER",
            consent_given=True,
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:list"))
        ids = [farmer.pk for farmer in response.context["object_list"]]
        self.assertEqual(ids, sorted(ids))

    def test_reports_start_with_choose_report_and_show_only_relevant_filters(self):
        self.client.force_login(self.staff)
        initial = self.client.get(reverse("reports:home"))
        self.assertEqual(initial.context["selected_report_type"], "")
        self.assertContains(initial, '<option value="">Choose a report</option>', html=True)
        self.assertContains(initial, 'data-filter-row="common" hidden')
        self.assertNotContains(initial, "Summarizes service requests by status")

        service_report = self.client.get(
            reverse("reports:home"),
            {"report_type": "service_status", "date_range": "all"},
        )
        self.assertContains(service_report, 'data-filter-row="status"')
        self.assertNotContains(service_report, 'data-filter-row="status" hidden')
        self.assertContains(service_report, 'data-filter-row="intervention" hidden')

        intervention_report = self.client.get(
            reverse("reports:home"),
            {"report_type": "intervention_registry", "date_range": "all"},
        )
        self.assertContains(intervention_report, 'data-filter-row="intervention"')
        self.assertNotContains(intervention_report, 'data-filter-row="intervention" hidden')
        self.assertContains(intervention_report, 'data-filter-row="status" hidden')

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

    def test_farmer_master_pdf_is_a_continuous_one_farmer_per_row_table(self):
        from pypdf import PdfReader

        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("reports:home"),
            {
                "report_type": "farmer_master",
                "format": "pdf",
                "date_range": "all",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        exported_text = "\n".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages
        )
        for heading in (
            "Farmer ID",
            "Farmer Name",
            "RSBSA ID",
            "Status",
            "Barangay",
            "Phone",
            "Livelihood",
            "Farm Records",
        ):
            self.assertIn(heading, exported_text)
        self.assertIn(self.farmer.record_id, exported_text)
        self.assertIn(self.farmer.full_name, exported_text)
        self.assertNotIn("FARMER INFORMATION", exported_text)
        self.assertNotIn("FARM PARCELS AND CROPS", exported_text)

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

    def test_farmer_master_preview_shows_farmer_information_without_barangay_graph(self):
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("reports:home"),
            {"report_type": "farmer_master", "date_range": "all"},
        )
        preview = response.context["report_preview"]
        self.assertFalse(preview["show_chart"])
        self.assertEqual(
            preview["headers"],
            [
                "Farmer ID",
                "Farmer Name",
                "RSBSA ID",
                "Registration Status",
                "Barangay",
                "Phone",
                "Livelihood",
                "Farm Records",
            ],
        )
        self.assertEqual(preview["rows"][0][0], self.farmer.record_id)
        self.assertEqual(preview["rows"][0][1], self.farmer.full_name)
        self.assertContains(response, "farmer-master-preview")
        self.assertNotContains(response, "Farmer Master List chart")

    def test_staff_dashboard_prioritizes_record_gaps_and_fixed_weather_location(self):
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
        attention = {
            item["key"]: item["count"]
            for item in response.context["attention_chart"]
        }
        self.assertEqual(attention["registration"], 0)
        self.assertEqual(attention["parcel"], 0)
        self.assertEqual(attention["mapping"], 1)
        self.assertEqual(attention["crop"], 0)
        self.assertEqual(attention["planting_date"], 0)
        self.assertEqual(response.context["area_planted"], Decimal("2.00"))
        self.assertNotIn("farmer_statistics", response.context)
        self.assertNotContains(response, "Farmer Statistics")
        self.assertContains(response, "Rosario, Batangas")
        self.assertContains(response, 'data-latitude="13.8442"')
        self.assertContains(response, "Records Needing Attention")
        self.assertContains(response, "Parcels without map pins")
        self.assertContains(response, "Service Request Overview")
        self.assertNotContains(response, 'data-card-url="/crops/"')
        self.assertNotContains(response, "View crop records")
        self.assertNotContains(response, "SUGGESTED CROP")
        self.assertNotContains(response, "Data reference")
        self.assertContains(response, 'class="dashboard-utility-row"')
        self.assertContains(response, "Wet season")
        self.assertNotContains(response, "Local FMIS data")
        self.assertNotContains(response, "Planning aid only")
        self.assertNotContains(response, "confidence")
        self.assertEqual(response.context["crop_recommendation"]["crop"], "Rice")
        self.assertEqual(response.context["crop_recommendation"]["confidence"], "Low")
        page = response.content.decode()
        self.assertLess(page.index("Records Needing Attention"), page.index("Service Request Overview"))
        self.assertLess(page.index("Rosario Weather"), page.index("Rosario reference"))
        self.assertNotContains(response, "Inventor")
        self.assertNotContains(response, "Pending Projects")
        self.assertNotContains(response, "Requests by Service")
        self.assertNotContains(response, "recorded requests")

    @override_settings(FMIS_FIELD_BASE_URL="https://field.fmis.example.gov.ph")
    def test_farmer_qr_uses_configured_authenticated_field_address(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:qr_print", args=[self.farmer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response.context["secure_url"].startswith(
                "https://field.fmis.example.gov.ph/farmers/field/"
            )
        )

    def test_missing_farmer_photo_returns_safe_authenticated_placeholder(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:photo", args=[self.farmer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

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
        self.assertContains(admin_response, "Backup &amp; Recovery Readiness")
        self.assertContains(admin_response, "Automatic schedule")
        self.assertContains(admin_response, "No backup has been recorded")
        self.assertNotContains(admin_response, "Manage User Accounts")
        self.assertNotContains(admin_response, "Review Audit Activity")

        admin_reports = self.client.get(reverse("reports:home"))
        self.assertContains(admin_reports, "Governance Reports")
        self.assertContains(admin_reports, "User Account Registry")
        self.assertContains(admin_reports, "Activity Audit Trail")
        self.assertContains(admin_reports, "data-download-form", count=3)
        self.assertNotContains(admin_reports, "System Report Builder")
        self.assertNotContains(admin_reports, "No report selected yet")

    def test_governance_report_buttons_download_every_pdf_and_csv(self):
        self.client.force_login(self.admin)
        for report_type in ("system_overview", "user_accounts", "activity_audit"):
            for output_format, content_type in (
                ("pdf", "application/pdf"),
                ("csv", "text/csv; charset=utf-8"),
            ):
                with self.subTest(report_type=report_type, output_format=output_format):
                    response = self.client.post(
                        reverse("reports:home"),
                        {
                            "report_type": report_type,
                            "date_range": "all",
                            "format": output_format,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["Content-Type"], content_type)
                    self.assertIn("attachment;", response["Content-Disposition"])

    def test_management_tables_do_not_show_export_controls(self):
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
            self.assertNotContains(page, "Export filtered records")
            self.assertNotContains(page, reverse("reports:management_export", args=[dataset]))
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
        self.assertIn("20 crop record(s)", locally_supported["evidence"])

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

    def test_operational_delete_actions_preserve_records(self):
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Archive workflow check",
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)

        self.client.post(reverse("crops:delete", args=[self.crop.pk]))
        self.crop.refresh_from_db()
        self.assertFalse(self.crop.is_active)
        self.assertIsNotNone(self.crop.archived_at)

        self.client.post(reverse("farm_parcels:delete", args=[self.parcel.pk]))
        self.parcel.refresh_from_db()
        self.assertFalse(self.parcel.is_active)
        self.assertTrue(CropRecord.objects.filter(pk=self.crop.pk).exists())

        self.client.post(reverse("farmers:delete", args=[self.farmer.pk]))
        self.farmer.refresh_from_db()
        self.assertFalse(self.farmer.is_active)
        self.assertTrue(FarmParcel.objects.filter(pk=self.parcel.pk).exists())

        self.client.post(reverse("service_requests:delete", args=[request_item.pk]))
        request_item.refresh_from_db()
        self.assertEqual(request_item.status, "CANCELLED")
        self.assertTrue(
            ServiceRequestHistory.objects.filter(
                service_request=request_item,
                action="CANCELLED",
                actor=self.staff,
            ).exists()
        )

    def test_archived_records_can_be_restored(self):
        self.crop.is_active = False
        self.crop.save(update_fields=["is_active"])
        self.parcel.is_active = False
        self.parcel.save(update_fields=["is_active"])
        self.farmer.is_active = False
        self.farmer.save(update_fields=["is_active"])
        self.client.force_login(self.staff)

        self.client.post(reverse("crops:delete", args=[self.crop.pk]), {"action": "restore"})
        self.client.post(
            reverse("farm_parcels:delete", args=[self.parcel.pk]), {"action": "restore"}
        )
        self.client.post(reverse("farmers:delete", args=[self.farmer.pk]), {"action": "restore"})
        self.crop.refresh_from_db()
        self.parcel.refresh_from_db()
        self.farmer.refresh_from_db()
        self.assertTrue(self.crop.is_active)
        self.assertTrue(self.parcel.is_active)
        self.assertTrue(self.farmer.is_active)

    def test_crop_area_cannot_overstate_non_intercrop_parcel_use(self):
        form = CropRecordForm(
            data={
                "parcel": self.parcel.pk,
                "crop_type": "Corn",
                "cropping_schedule": "Jan-Mar",
                "area_hectares": "1.00",
                "number_of_heads": "",
                "is_organic": "False",
                "is_intercrop": "False",
                "planting_date": date.today().isoformat(),
                "harvest_date": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("exceeds this parcel", form.errors["area_hectares"][0])

    def test_farmer_supporting_documents_require_staff_access(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            document = FarmerDocument.objects.create(
                farmer=self.farmer,
                document_type="OTHER",
                description="Access-control test",
                file=SimpleUploadedFile("private.txt", b"protected farmer record"),
            )
            url = reverse("farmers:document", args=[document.pk])
            anonymous = self.client.get(url)
            self.assertEqual(anonymous.status_code, 302)

            self.client.force_login(self.staff)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")
            self.assertTrue(
                ActivityLog.objects.filter(
                    title="Supporting Document Accessed",
                    actor=self.staff,
                ).exists()
            )
            response.close()

    def test_missing_farmer_supporting_document_redirects_without_server_error(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            document = FarmerDocument.objects.create(
                farmer=self.farmer,
                document_type="ADDITIONAL",
                description="Missing legacy upload",
                file="farm_documents/file-that-no-longer-exists.pdf",
            )
            self.client.force_login(self.staff)
            response = self.client.get(reverse("farmers:document", args=[document.pk]))
            self.assertRedirects(response, reverse("farmers:detail", args=[self.farmer.pk]))
            detail = self.client.get(reverse("farmers:detail", args=[self.farmer.pk]))
            self.assertContains(detail, "File unavailable")
            self.assertNotContains(detail, reverse("farmers:document", args=[document.pk]))
            self.assertTrue(
                ActivityLog.objects.filter(
                    title="Supporting Document Unavailable",
                    actor=self.staff,
                ).exists()
            )

    def test_in_app_notifications_are_private_linked_and_markable_as_read(self):
        User = get_user_model()
        recipient = User.objects.create_user(
            username="notificationstaff",
            password="Ready4Field!Secure",
            role="STAFF",
            email="notice@example.com",
        )
        activity = log_activity(self.admin, "POST /farmers/new/", "/farmers/new/")

        from apps.notifications.models import Notification
        from apps.settings_page.models import UserPreference

        notification = Notification.objects.get(
            recipient=recipient,
            source_activity=activity,
        )
        self.assertFalse(notification.is_read)
        self.assertIn(self.admin.display_name, notification.message)
        self.assertNotIn("record was updated", notification.message.casefold())
        self.assertNotIn("/farmers/", notification.message)
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
        log_activity(self.admin, "POST /farmers/new/", "/farmers/new/")
        self.assertEqual(Notification.objects.filter(recipient=recipient).count(), 1)

        settings_page = self.client.get(reverse("settings_page:home"))
        self.assertNotContains(settings_page, "Email Notifications")
        self.assertNotContains(settings_page, "Weekly Summary")
        self.assertContains(settings_page, "In-App Notifications")

    def test_security_notifications_use_plain_language(self):
        from apps.activity_logs.services import record_event
        from apps.notifications.models import Notification

        record_event(
            actor=self.staff,
            title="Access denied",
            module="Security",
            description="Technical security detail",
            path="/dashboard/admin/",
            status="Warning",
            target_label="/dashboard/admin/",
        )
        notification = Notification.objects.filter(recipient=self.admin).latest("created_at")
        self.assertEqual(notification.title, "Restricted page blocked")
        self.assertIn("not available for their account", notification.message)
        self.assertIn("No changes were made", notification.message)
        self.assertNotIn("/dashboard/admin/", notification.message)

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
        settings_page = self.client.get(reverse("settings_page:home"))
        self.assertNotContains(settings_page, "System Configuration &amp; Localization")
        self.assertNotContains(settings_page, "Session Policy")
        self.assertNotContains(settings_page, "Idle Session Timeout")
        self.assertContains(settings_page, "Backup &amp; Recovery")

    def test_staff_can_upload_and_remove_a_profile_photo(self):
        from apps.settings_page.models import UserPreference

        image_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        self.client.force_login(self.staff)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("settings_page:home"),
                {
                    "first_name": self.staff.first_name,
                    "last_name": self.staff.last_name,
                    "email": self.staff.email,
                    "phone_number": self.staff.phone_number,
                    "theme": "system",
                    "primary_color": "#008552",
                    "in_app_notifications": "on",
                    "profile_photo": SimpleUploadedFile(
                        "profile.png", image_bytes, content_type="image/png"
                    ),
                },
            )
            self.assertRedirects(response, reverse("settings_page:home"))
            preference = UserPreference.objects.get(user=self.staff)
            self.assertTrue(preference.profile_photo.name.startswith("account_profiles/"))
            stored_name = preference.profile_photo.name
            self.assertTrue(preference.profile_photo.storage.exists(stored_name))

            settings_page = self.client.get(reverse("settings_page:home"))
            self.assertContains(settings_page, preference.profile_photo.url)
            self.assertContains(settings_page, "Remove photo")

            response = self.client.post(
                reverse("settings_page:home"),
                {
                    "first_name": self.staff.first_name,
                    "last_name": self.staff.last_name,
                    "email": self.staff.email,
                    "phone_number": self.staff.phone_number,
                    "theme": "system",
                    "primary_color": "#008552",
                    "in_app_notifications": "on",
                    "remove_profile_photo": "on",
                },
            )
            self.assertRedirects(response, reverse("settings_page:home"))
            preference.refresh_from_db()
            self.assertFalse(preference.profile_photo)
            self.assertFalse(preference.profile_photo.storage.exists(stored_name))

    def test_system_theme_is_default_and_resolves_before_page_content(self):
        self.client.force_login(self.staff)
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'data-theme-preference="system"')
        self.assertContains(dashboard, 'prefers-color-scheme: dark')
        self.assertContains(dashboard, "document.documentElement.style.colorScheme")

        settings_page = self.client.get(reverse("settings_page:home"))
        self.assertContains(settings_page, "System (Recommended)")
        self.assertNotContains(settings_page, "follows your computer's light or dark appearance")
        self.assertNotContains(settings_page, "Primary Color")
        self.assertNotContains(settings_page, "Profile &amp; Account")
        self.assertContains(settings_page, "Profile Details")

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
        self.assertContains(response, "Setup still needs:")
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
