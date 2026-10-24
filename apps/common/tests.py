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
from apps.common.forms import InlineValidationMixin
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
from apps.interventions.forms import InterventionForm
from apps.interventions.models import Intervention
from apps.reports.export import build_report, build_system_report
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.forms import ServiceRequestForm
from apps.service_requests.models import ServiceRequest, ServiceRequestHistory
from config.startup import prewarm_wsgi_application


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

    def test_public_landing_and_authentication_use_separate_pages(self):
        for name in (
            "authentication:landing",
            "authentication:login",
            "authentication:password_reset",
            "authentication:privacy",
            "authentication:terms",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
        self.assertContains(
            self.client.get(reverse("authentication:privacy")), "Information collected"
        )
        landing = self.client.get(reverse("authentication:landing"))
        self.assertContains(landing, "rice-field-data-collection.webp")
        self.assertContains(landing, "images/brand/fmis-logo-display.webp")
        self.assertNotContains(landing, 'id="heroCarousel"')
        self.assertNotContains(landing, "data-carousel-next")
        self.assertNotContains(landing, "scope-carousel")
        self.assertContains(landing, "data-service-next")
        self.assertNotContains(landing, "feature-toggle")
        self.assertContains(landing, "landingProgress")
        self.assertContains(landing, "js/landing.min.js")
        self.assertContains(landing, "script defer")
        self.assertContains(landing, reverse("authentication:login"))
        self.assertContains(landing, "showcase-login-button")
        self.assertNotContains(landing, "landing-signin-form")

        login_page = self.client.get(reverse("authentication:login"))
        self.assertContains(login_page, "landing-signin-form")
        self.assertContains(login_page, reverse("authentication:password_reset"))
        self.assertNotContains(login_page, "data-service-next")

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
        login_page = self.client.get(reverse("authentication:login"))
        self.assertContains(login_page, "data-password-toggle", count=1)
        self.assertContains(login_page, 'aria-controls="id_password"')
        self.assertContains(login_page, "password-toggle.min.js")

        self.client.force_login(self.admin)
        account_form = self.client.get(reverse("accounts:create"))
        self.assertEqual(account_form.status_code, 200)
        self.assertContains(account_form, "data-password-toggle", count=2)
        self.assertContains(account_form, 'class="account-password-toggle"', count=2)
        self.assertContains(account_form, 'aria-controls="id_password1"')
        self.assertContains(account_form, 'aria-controls="id_password2"')

    def test_authentication_accepts_valid_credentials_and_rejects_invalid(self):
        login_error = self.client.post(
            reverse("authentication:login"),
            {"username": "staff", "password": "wrong"},
        )
        self.assertEqual(login_error.status_code, 200)
        self.assertContains(login_error, "landing-field-error")
        self.assertContains(login_error, "The username or password is incorrect.")
        self.assertContains(login_error, "has-error", count=2)
        self.assertContains(login_error, "novalidate")
        response = self.client.post(
            reverse("authentication:login"),
            {"username": "staff", "password": "StrongPass123!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.post(reverse("authentication:landing")).status_code,
            405,
        )

    def test_form_errors_are_server_rendered_below_red_highlighted_fields(self):
        form = InterventionForm(data={})

        self.assertFalse(form.is_valid())
        status_html = str(form["status"])
        status_errors = str(form["status"].errors)
        self.assertIn('class="form-control is-invalid"', status_html)
        self.assertIn('aria-invalid="true"', status_html)
        self.assertIn('aria-describedby="id_status_error"', status_html)
        self.assertIn('id="id_status_error"', status_errors)
        self.assertNotIn(" required", status_html)
        self.assertEqual(
            form.fields["service_request"].label, "Related service request"
        )

    def test_password_change_uses_normal_server_rendered_validation(self):
        self.client.force_login(self.staff)

        response = self.client.post(reverse("settings_page:change_password"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "novalidate")
        self.assertContains(response, 'name="old_password"')
        self.assertContains(response, "is-invalid", count=3)
        self.assertContains(response, "This field is required.", count=3)

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

    def test_admin_can_permanently_delete_account_and_reuse_contact_details(self):
        User = get_user_model()
        disposable = User.objects.create_user(
            username="staff2",
            email="staff2@example.com",
            phone_number="09924526840",
            password="Ready4Field!Secure",
            role="STAFF",
            is_active=False,
        )
        historical_activity = ActivityLog.objects.create(
            actor=disposable,
            action="POST /farmers/new/",
            path="/farmers/new/",
            title="Farmer Record Created",
            module="Farmers",
            description="staff2 created a farmer record.",
        )
        historical_request = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Historical seed request",
            assigned_to=disposable,
        )
        request_history = ServiceRequestHistory.objects.create(
            service_request=historical_request,
            actor=disposable,
            action="CREATED",
            to_status="PENDING",
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("accounts:delete", args=[disposable.pk]),
            {"action": "delete"},
        )

        self.assertRedirects(response, reverse("accounts:list"))
        disposable.refresh_from_db()
        self.assertTrue(disposable.is_deleted)
        self.assertFalse(disposable.is_active)
        self.assertEqual(disposable.deleted_username, "staff2")
        self.assertEqual(disposable.email, "")
        self.assertEqual(disposable.phone_number, "")
        self.assertFalse(disposable.has_usable_password())
        historical_activity.refresh_from_db()
        self.assertEqual(historical_activity.actor_id, disposable.pk)
        self.assertEqual(historical_activity.actor.audit_username, "staff2")
        historical_request.refresh_from_db()
        request_history.refresh_from_db()
        self.assertEqual(historical_request.assigned_to_id, disposable.pk)
        self.assertEqual(request_history.actor_id, disposable.pk)
        account_list = self.client.get(reverse("accounts:list"))
        self.assertNotContains(account_list, disposable.username)
        self.assertTrue(
            ActivityLog.objects.filter(
                title="User Account Deleted",
                target_label="staff2",
            ).exists()
        )
        replacement = AccountForm(
            data={
                "username": "staff2",
                "email": "staff2@example.com",
                "phone_number": "09924526840",
                "password1": "Ready4Field!Secure",
                "password2": "Ready4Field!Secure",
            }
        )
        self.assertTrue(replacement.is_valid(), replacement.errors)

    def test_current_admin_cannot_delete_own_account(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("accounts:delete", args=[self.admin.pk]),
            {"action": "delete"},
        )

        self.assertRedirects(response, reverse("accounts:list"))
        self.assertTrue(get_user_model().objects.filter(pk=self.admin.pk).exists())

    def test_health_check_reports_database_readiness_without_internal_details(self):
        response = self.client.get(reverse("health_check"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-store", response["Cache-Control"])

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

    def test_dedicated_login_page_uses_secure_authentication_flow(self):
        response = self.client.post(
            reverse("authentication:login"),
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
            reverse("authentication:login"),
            {
                "username": "staff",
                "password": "StrongPass123!",
                "remember_me": "on",
            },
        )
        session = self.client.session
        session["fmis_last_activity"] = int(time.time())
        session["fmis_remember_until"] = int(time.time()) - 1
        session.save()
        response = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("authentication:login")))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_remembered_login_stays_active_during_idle_period(self):
        self.client.post(
            reverse("authentication:login"),
            {"username": "staff", "password": "StrongPass123!", "remember_me": "on"},
        )
        session = self.client.session
        session["fmis_last_activity"] = int(time.time()) - 901
        session.save()
        cache.set("fmis:session-timeout-minutes", 15, 60)
        response = self.client.get(reverse("dashboard:staff_home"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

    def test_login_page_restores_remembered_username_without_storing_password(self):
        response = self.client.get(reverse("authentication:login"))
        self.assertContains(response, 'autocomplete="on"')
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, 'data-remember-seconds="604800"')
        self.assertContains(response, 'fmis.remembered-login')
        self.assertNotContains(response, "password: username.value")

    def test_unremembered_login_ends_with_the_browser_session(self):
        response = self.client.post(
            reverse("authentication:login"),
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
        self.assertTrue(response.url.startswith(reverse("authentication:login")))
        self.assertIn("next=%2Fdashboard%2F", response.url)
        self.assertNotIn("_auth_user_id", self.client.session)

        login_page = self.client.get(response.url)
        timeout_message = "Your session expired due to inactivity. Please sign in again."
        self.assertContains(login_page, timeout_message)
        login_response = self.client.post(
            reverse("authentication:login"),
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
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("already linked", form.errors["valid_id_number"][0])

    def test_shared_validation_rejects_blank_and_non_numeric_input_and_normalizes_spacing(self):
        class AuditForm(InlineValidationMixin, django_forms.Form):
            name = django_forms.CharField()
            quantity = django_forms.IntegerField()
            notes = django_forms.CharField(required=False)

        invalid = AuditForm(data={"name": "   ", "quantity": "12bags"})
        self.assertFalse(invalid.is_valid())
        self.assertIn("name", invalid.errors)
        self.assertIn("quantity", invalid.errors)

        valid = AuditForm(
            data={"name": "  Seed   Distribution  ", "quantity": "12", "notes": "  Ready   for release  "}
        )
        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.cleaned_data["name"], "Seed Distribution")
        self.assertEqual(valid.cleaned_data["notes"], "Ready for release")

    def test_farmer_names_reject_digits_and_normalize_all_caps(self):
        base = {
            "last_name": "DELA CRUZ",
            "first_name": "MARIA",
            "sex": "FEMALE",
            "birth_date": "1992-04-08",
            "place_of_birth": "ROSARIO",
            "mother_maiden_name": "SANTOS",
            "barangay": "Alupay",
            "phone_number": "09181234567",
            "civil_status": "SINGLE",
            "valid_id_type": "National ID",
            "valid_id_number": "9999888877776666",
            "livelihood": "FARMER",
            "is_indigenous": "False",
            "is_pwd": "False",
            "is_four_ps": "False",
            "consent_given": "on",
        }
        form = FarmerRegistrationForm(data=base)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["first_name"], "Maria")
        self.assertEqual(form.cleaned_data["last_name"], "Dela Cruz")

        invalid = FarmerRegistrationForm(data={**base, "first_name": "Maria2"})
        self.assertFalse(invalid.is_valid())
        self.assertIn("first_name", invalid.errors)

    def test_service_request_subject_is_generated_from_request_type(self):
        form = ServiceRequestForm(
            data={
                "farmer": self.farmer.pk,
                "service": self.service.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
                "notes": "",
                "assigned_to": self.staff.pk,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("subject", form.fields)
        self.assertEqual(form.save().subject, self.service.name)

    def test_service_request_accepts_a_barangay_scope_without_one_farmer(self):
        form = ServiceRequestForm(
            data={
                "scope": "BARANGAY",
                "target_barangay": "Bulihan",
                "service": self.service.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
                "notes": "Barangay-wide seed assistance request.",
                "assigned_to": self.staff.pk,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        request_item = form.save()
        self.assertEqual(request_item.scope, "BARANGAY")
        self.assertEqual(request_item.target_barangay, "Bulihan")
        self.assertIsNone(request_item.farmer)
        self.assertEqual(
            request_item.beneficiary_label,
            "All active farmers in Brgy. Bulihan",
        )

    def test_service_request_scope_requires_its_matching_beneficiary(self):
        individual = ServiceRequestForm(
            data={
                "scope": "INDIVIDUAL",
                "service": self.service.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
            }
        )
        barangay = ServiceRequestForm(
            data={
                "scope": "BARANGAY",
                "service": self.service.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
            }
        )

        self.assertFalse(individual.is_valid())
        self.assertIn("farmer", individual.errors)
        self.assertFalse(barangay.is_valid())
        self.assertIn("target_barangay", barangay.errors)

    def test_barangay_requests_and_interventions_reject_zero_active_farmers(self):
        Farmer.objects.filter(barangay="Mabato").update(is_active=False)
        request_form = ServiceRequestForm(
            data={
                "scope": "BARANGAY",
                "target_barangay": "Mabato",
                "service": self.service.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
            }
        )
        intervention_form = InterventionForm(
            data={
                "scope": "BARANGAY",
                "target_barangay": "Mabato",
                "status": "SCHEDULED",
                "intervention_type": "TRAINING",
                "intervention_date": date.today().isoformat(),
                "description": "Barangay training",
                "provider": "Office for Agricultural Services",
            }
        )

        self.assertFalse(request_form.is_valid())
        self.assertIn("no active farmers", request_form.errors["target_barangay"][0])
        self.assertFalse(intervention_form.is_valid())
        self.assertIn("no active farmers", intervention_form.errors["target_barangay"][0])

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

    def test_service_request_farmer_picker_is_lazy_and_group_services_require_barangay(self):
        training = ServiceCatalog.objects.get(code="TRAINING")
        blank_form = ServiceRequestForm()
        self.assertEqual(blank_form.fields["farmer"].queryset.count(), 0)
        self.assertEqual(
            blank_form.fields["farmer"].widget.attrs["data-search-url"],
            reverse("interventions:farmer_search"),
        )
        self.assertIn(
            str(training.pk),
            blank_form.fields["service"].widget.attrs["data-barangay-only-values"].split(","),
        )

        individual = ServiceRequestForm(
            data={
                "scope": "INDIVIDUAL",
                "farmer": self.farmer.pk,
                "service": training.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
            }
        )
        self.assertFalse(individual.is_valid())
        self.assertIn("barangay recipients", individual.errors["service"][0])
        self.assertEqual(individual.fields["farmer"].queryset.get(), self.farmer)

        barangay = ServiceRequestForm(
            data={
                "scope": "BARANGAY",
                "target_barangay": self.farmer.barangay,
                "service": training.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
            }
        )
        self.assertTrue(barangay.is_valid(), barangay.errors)

    def test_farmer_type_is_a_single_dropdown(self):
        form = FarmerRegistrationForm()
        self.assertIsInstance(form.fields["livelihood"].widget, django_forms.Select)
        self.assertNotIn("activities", form.fields)
        self.assertEqual(
            [value for value, _label in form.fields["livelihood"].choices if value],
            [value for value, _label in Farmer.LIVELIHOOD_CHOICES],
        )

    def test_farmer_list_filters_registration_status_instead_of_sex(self):
        encoded = Farmer.objects.create(
            first_name="Encoded",
            last_name="Farmer",
            barangay="Alupay",
            registration_status="ENCODED",
            consent_given=True,
        )
        self.client.force_login(self.staff)
        page = self.client.get(
            reverse("farmers:list"), {"registration_status": "ENCODED"}
        )
        self.assertContains(page, encoded.record_id)
        self.assertNotContains(page, self.farmer.record_id)
        self.assertContains(page, "Registration Status")
        self.assertContains(page, "Record Availability")
        self.assertNotContains(page, 'name="sex"')

    def test_farmer_detail_returns_to_last_filtered_list_page(self):
        self.client.force_login(self.staff)
        return_url = reverse("farmers:list") + "?page=1"
        list_page = self.client.get(return_url)
        detail_url = reverse("farmers:detail", args=[self.farmer.pk])

        self.assertContains(list_page, f'{detail_url}?next=')
        detail_page = self.client.get(detail_url, {"next": return_url})
        self.assertContains(detail_page, f'href="{return_url}"')

        reopened_detail = self.client.get(detail_url)
        self.assertContains(reopened_detail, f'href="{return_url}"')

    def test_farmer_detail_rejects_external_return_url(self):
        self.client.force_login(self.staff)
        detail_url = reverse("farmers:detail", args=[self.farmer.pk])
        page = self.client.get(detail_url, {"next": "https://example.com/steal"})
        self.assertContains(page, f'href="{reverse("farmers:list")}"')

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
            },
            files={
                "rsbsa_form": SimpleUploadedFile(
                    "rsbsa.pdf", b"%PDF-1.4\nRSBSA test\n%%EOF", content_type="application/pdf"
                )
            },
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
            },
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

    def _rsbsa_scan_image(self, size=(1200, 1600)):
        from PIL import Image

        output = BytesIO()
        Image.new("RGB", size, "white").save(output, format="JPEG")
        return SimpleUploadedFile(
            "rsbsa-page-1.jpg", output.getvalue(), content_type="image/jpeg"
        )

    def test_registration_page_offers_review_first_rsbsa_capture(self):
        self.client.force_login(self.staff)
        with override_settings(OPENAI_API_KEY="configured-for-test"):
            response = self.client.get(reverse("farmers:create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload RSBSA")
        self.assertContains(response, "Use camera")
        self.assertContains(response, reverse("farmers:scan_rsbsa"))
        self.assertNotContains(response, 'capture="environment"')
        self.assertContains(response, 'id="rsbsaCameraModal"')
        self.assertContains(response, 'id="rsbsaCameraCapture"')
        self.assertContains(response, "rsbsa-camera.js")
        self.assertContains(response, "Review every highlighted value")
        self.assertContains(response, 'id="rsbsaScanSelection"')
        self.assertContains(response, "RSBSA form")
        self.assertContains(response, "(optional)")
        self.assertContains(response, "or continue below and enter the details manually")
        self.assertNotContains(response, 'id="rsbsaScanPreviewImage"')
        self.assertContains(response, 'id="rsbsaScanRemove"')
        self.assertContains(response, "Remove selected RSBSA form")
        self.assertContains(response, 'data-compact-file-upload')
        self.assertContains(response, "Select File")
        self.assertContains(response, "Upload a JPG, PNG, or WEBP image no larger than 8 MB.")
        self.assertContains(response, "registration-draft.js")
        self.assertNotContains(response, "No RSBSA image selected.")
        self.assertNotContains(response, "This workflow follows the RSBSA Enrollment Form")
        self.assertContains(response, 'id="fmisNetworkLoading"')

        with override_settings(OPENAI_API_KEY=""):
            unconfigured_response = self.client.get(reverse("farmers:create"))
        self.assertNotContains(
            unconfigured_response, "Automatic reading needs server configuration."
        )
        self.assertNotContains(
            unconfigured_response, "Automatic reading is not configured"
        )

    def test_rsbsa_scanner_accepts_standard_laptop_camera_resolution(self):
        from apps.farmers.rsbsa_scan import _validated_upload

        raw, content_type, input_kind = _validated_upload(
            self._rsbsa_scan_image(size=(1280, 720))
        )

        self.assertTrue(raw)
        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(input_kind, "image")

    @override_settings(OPENAI_API_KEY="")
    def test_rsbsa_scanner_reports_when_server_configuration_is_missing(self):
        self.client.force_login(self.staff)
        farmer_count = Farmer.objects.count()

        response = self.client.post(
            reverse("farmers:scan_rsbsa"),
            {"rsbsa_scan": self._rsbsa_scan_image()},
        )

        self.assertEqual(response.status_code, 503)
        self.assertIn("not configured", response.json()["error"])
        self.assertEqual(Farmer.objects.count(), farmer_count)

    @override_settings(
        OPENAI_API_KEY="test-project-key",
        OPENAI_API_BASE="https://api.openai.com/v1",
        RSBSA_OCR_MODEL="gpt-5.4-mini",
        RSBSA_OCR_TIMEOUT_SECONDS=60,
    )
    @patch("apps.farmers.rsbsa_scan.requests.post")
    def test_rsbsa_scanner_returns_sanitized_profile_without_saving(self, post):
        from apps.farmers.rsbsa_scan import PROFILE_FIELDS

        fields = {name: "" for name in PROFILE_FIELDS}
        fields.update(
            {
                "last_name": "Dela Cruz",
                "first_name": "Maria",
                "sex": "FEMALE",
                "birth_date": "1992-04-08",
                "barangay": "alupay",
                "phone_number": "+63 918 123 4567",
                "civil_status": "SINGLE",
                "livelihood": "FARMER",
                "is_pwd": "False",
                "valid_id_type": "National ID",
                "valid_id_number": "9999888877776666",
            }
        )
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "is_rsbsa_form": True,
                                    "form_version": "01-2024",
                                    "detected_anchors": [
                                        "da_logo",
                                        "registry_title",
                                        "enrollment_form_title",
                                        "part_1_personal_information",
                                        "part_2_livelihood_profile",
                                    ],
                                    "fields": fields,
                                    "needs_review": ["last_name"],
                                    "warnings": ["Check the handwritten surname."],
                                }
                            ),
                        }
                    ],
                }
            ]
        }
        self.client.force_login(self.staff)
        farmer_count = Farmer.objects.count()

        response = self.client.post(
            reverse("farmers:scan_rsbsa"),
            {"rsbsa_scan": self._rsbsa_scan_image()},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["fields"]["barangay"], "Alupay")
        self.assertEqual(payload["fields"]["phone_number"], "09181234567")
        self.assertIn("last_name", payload["needs_review"])
        self.assertTrue(payload["scan_token"])
        self.assertEqual(Farmer.objects.count(), farmer_count)
        api_request = post.call_args.kwargs
        self.assertFalse(api_request["json"]["store"])
        self.assertEqual(api_request["json"]["model"], "gpt-5.4-mini")
        image_input = api_request["json"]["input"][0]["content"][1]
        self.assertTrue(image_input["image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(image_input["detail"], "original")

    def test_rsbsa_scanner_rejects_non_image_without_calling_provider(self):
        self.client.force_login(self.staff)
        with override_settings(OPENAI_API_KEY="test-project-key"), patch(
            "apps.farmers.rsbsa_scan.requests.post"
        ) as post:
            response = self.client.post(
                reverse("farmers:scan_rsbsa"),
                {
                    "rsbsa_scan": SimpleUploadedFile(
                        "not-a-form.jpg", b"not an image", content_type="image/jpeg"
                    )
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a readable", response.json()["error"])
        post.assert_not_called()

    @override_settings(
        OPENAI_API_KEY="test-project-key",
        OPENAI_API_BASE="https://api.openai.com/v1",
        RSBSA_OCR_MODEL="gpt-5.4-mini",
    )
    @patch("apps.farmers.rsbsa_scan.requests.post")
    def test_rsbsa_scanner_reads_pdf_and_requires_official_form_anchors(self, post):
        from apps.farmers.rsbsa_scan import PROFILE_FIELDS

        fields = {name: "" for name in PROFILE_FIELDS}
        fields.update({"last_name": "Santos", "first_name": "Ana"})
        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "is_rsbsa_form": True,
                        "form_version": "01-2024",
                        "detected_anchors": [
                            "da_logo",
                            "registry_title",
                            "enrollment_form_title",
                            "part_1_personal_information",
                            "part_2_livelihood_profile",
                        ],
                        "fields": fields,
                        "needs_review": [],
                        "warnings": [],
                    }),
                }],
            }]
        }
        self.client.force_login(self.staff)
        pdf_bytes = b"%PDF-1.4\nscanned page\n%%EOF"

        response = self.client.post(
            reverse("farmers:scan_rsbsa"),
            {"rsbsa_scan": SimpleUploadedFile(
                "rsbsa.pdf", pdf_bytes, content_type="application/pdf"
            )},
        )

        self.assertEqual(response.status_code, 200)
        file_input = post.call_args.kwargs["json"]["input"][0]["content"][1]
        self.assertEqual(file_input["type"], "input_file")
        self.assertTrue(file_input["file_data"].startswith("data:application/pdf;base64,"))
        self.assertTrue(response.json()["scan_token"])

        post.return_value.json.return_value["output"][0]["content"][0]["text"] = json.dumps({
            "is_rsbsa_form": True,
            "form_version": "",
            "detected_anchors": ["registry_title"],
            "fields": fields,
            "needs_review": [],
            "warnings": [],
        })
        rejected = self.client.post(
            reverse("farmers:scan_rsbsa"),
            {"rsbsa_scan": SimpleUploadedFile(
                "unrelated.pdf", pdf_bytes, content_type="application/pdf"
            )},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("does not match", rejected.json()["error"])

    def _valid_registration_payload(self):
        from apps.farmers.rsbsa_scan import build_scan_token

        rsbsa_bytes = b"%PDF-1.4\nRequired RSBSA form\n%%EOF"
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
            "rsbsa_form": SimpleUploadedFile(
                "rsbsa-form.pdf",
                rsbsa_bytes,
                content_type="application/pdf",
            ),
            "rsbsa_scan_token": build_scan_token(rsbsa_bytes),
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
        self.assertEqual(saved.documents.count(), 2)
        self.assertTrue(saved.documents.filter(document_type="RSBSA_FORM").exists())

    def test_registration_rejects_an_unverified_rsbsa_upload(self):
        self.client.force_login(self.staff)
        payload = self._valid_registration_payload()
        payload.pop("rsbsa_scan_token")

        response = self.client.post(reverse("farmers:create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("rsbsa_form", response.context["profile_form"].errors)
        self.assertFalse(Farmer.objects.filter(valid_id_number="9999888877776666").exists())

    def test_registration_can_be_encoded_without_an_rsbsa_upload(self):
        self.client.force_login(self.staff)
        payload = self._valid_registration_payload()
        payload.pop("rsbsa_form")
        payload.pop("rsbsa_scan_token")

        response = self.client.post(reverse("farmers:create"), payload)

        self.assertEqual(response.status_code, 302, response.context)
        saved = Farmer.objects.get(valid_id_number="9999888877776666")
        self.assertFalse(saved.documents.filter(document_type="RSBSA_FORM").exists())
        self.assertTrue(saved.documents.filter(document_type="VALID_ID").exists())

    def test_registration_requires_valid_id_type_and_number(self):
        self.client.force_login(self.staff)
        payload = self._valid_registration_payload()
        payload["valid_id_type"] = ""
        payload["valid_id_number"] = ""
        payload["documents-0-document_type"] = "OWNERSHIP"
        payload["documents-0-description"] = "Barangay-certified tenure record"

        response = self.client.post(reverse("farmers:create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertIn("valid_id_type", response.context["profile_form"].errors)
        self.assertIn("valid_id_number", response.context["profile_form"].errors)
        self.assertFalse(Farmer.objects.filter(first_name="Maria", last_name="Dela Cruz").exists())

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
        self.assertEqual(create_page.status_code, 200)
        self.assertContains(create_page, 'id="rsbsaRegistration"')
        self.assertNotContains(create_page, 'name="registration_status"')

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
        detail = self.client.get(
            reverse("service_requests:detail", args=[request_record.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertNotContains(detail, "Record Delivered Intervention")

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
        self.assertContains(crop_response, "Commodity &amp; Production Information")
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
        self.assertContains(saved_detail, "Update record saved.")
        self.assertContains(saved_detail, "now recorded in Update History")
        history_page = self.client.get(reverse("farmers:history", args=[self.farmer.pk]))
        self.assertEqual(history_page.status_code, 200)
        self.assertContains(history_page, "Farmer Update Record History")
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
            ("farmers", self.farmer.pk, "Farmer Update Record History"),
            ("farm_parcels", self.parcel.pk, "Farm Parcel Update Record History"),
            ("crops", self.crop.pk, "Commodity Update Record History"),
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

    def test_in_progress_service_request_tracks_intervention_through_completion(self):
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
                "status": "SCHEDULED",
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
        self.assertEqual(request_item.status, "IN_PROGRESS")

        response = self.client.post(
            reverse("interventions:edit", args=[intervention.pk]),
            {
                "scope": "INDIVIDUAL",
                "farmer": self.farmer.pk,
                "service_request": request_item.pk,
                "status": "COMPLETED",
                "intervention_type": "SEEDS",
                "intervention_date": date.today().isoformat(),
                "description": "Certified rice seed delivered",
                "quantity": "2",
                "unit": "bags",
                "provider": "Office for Agricultural Services",
            },
        )
        self.assertRedirects(response, reverse("interventions:list"))
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

    def test_service_request_requires_registered_intervention_before_completion(self):
        self.client.force_login(self.staff)
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject=self.service.name,
            priority="LOW",
            status="IN_PROGRESS",
            notes="Training and farm advisory delivered.",
            assigned_to=self.staff,
        )
        payload = {
            "farmer": self.farmer.pk,
            "service": self.service.pk,
            "priority": "LOW",
            "status": "COMPLETED",
            "notes": request_item.notes,
            "assigned_to": self.staff.pk,
        }

        response = self.client.post(
            reverse("service_requests:edit", args=[request_item.pk]), payload
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Register this service request in Interventions before marking it Completed.",
        )
        request_item.refresh_from_db()
        self.assertEqual(request_item.status, "IN_PROGRESS")
        self.assertFalse(Intervention.objects.filter(service_request=request_item).exists())

        intervention = Intervention.objects.create(
            farmer=self.farmer,
            service_request=request_item,
            status="SCHEDULED",
            intervention_type="TRAINING",
            intervention_date=date.today(),
            description="Scheduled training and farm advisory",
            recorded_by=self.staff,
        )
        response = self.client.post(
            reverse("service_requests:edit", args=[request_item.pk]), payload
        )
        self.assertRedirects(response, reverse("service_requests:list"))
        request_item.refresh_from_db()
        self.assertEqual(request_item.status, "COMPLETED")
        intervention.refresh_from_db()
        self.assertEqual(intervention.status, "COMPLETED")
        self.assertEqual(intervention.farmer, self.farmer)
        self.assertEqual(intervention.recorded_by, self.staff)
        recipient = intervention.recipients.get(farmer=self.farmer)
        self.assertEqual(recipient.status, "RECEIVED")
        self.assertEqual(recipient.received_at, intervention.intervention_date)

        self.assertEqual(
            Intervention.objects.filter(service_request=request_item).count(), 1
        )

    def test_pending_request_is_available_and_prefills_intervention_type(self):
        self.client.force_login(self.staff)
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject=self.service.name,
            priority="MEDIUM",
            status="PENDING",
            assigned_to=self.staff,
        )

        response = self.client.get(reverse("interventions:create"))
        self.assertContains(response, request_item.request_id)
        self.assertContains(response, self.service.name)

        linked = self.client.get(
            reverse("interventions:create"),
            {"service_request": request_item.pk},
        )
        self.assertEqual(linked.status_code, 200)
        self.assertEqual(linked.context["form"].initial["farmer"], self.farmer)
        self.assertEqual(linked.context["form"].initial["service_request"], request_item)
        self.assertEqual(linked.context["form"].initial["intervention_type"], "SEEDS")
        self.assertContains(linked, 'data-intervention-type="SEEDS"')
        self.assertContains(linked, f'data-farmer-id="{self.farmer.pk}"')

    def test_linked_request_rejects_mismatched_farmer_and_intervention_type(self):
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject=self.service.name,
            priority="MEDIUM",
            status="PENDING",
            assigned_to=self.staff,
        )
        another_farmer = Farmer.objects.create(
            first_name="Other",
            last_name="Farmer",
            barangay="Balibago",
        )
        form = InterventionForm(
            data={
                "scope": "SELECTED",
                "farmer": another_farmer.pk,
                "service_request": request_item.pk,
                "status": "SCHEDULED",
                "intervention_type": "TRAINING",
                "intervention_date": "2026-10-18",
                "description": "Linked assistance",
                "provider": "Office for Agricultural Services",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.cleaned_data["scope"], "INDIVIDUAL")
        self.assertEqual(form.cleaned_data["farmer"], self.farmer)
        self.assertEqual(form.cleaned_data["intervention_type"], "SEEDS")
        self.assertIn("scope", form.errors)
        self.assertIn("farmer", form.errors)
        self.assertIn("intervention_type", form.errors)

    def test_barangay_request_controls_intervention_scope_and_recipients(self):
        second_farmer = Farmer.objects.create(
            first_name="Lorna",
            last_name="Reyes",
            barangay=self.farmer.barangay,
            consent_given=True,
        )
        other_farmer = Farmer.objects.create(
            first_name="Mario",
            last_name="Cruz",
            barangay="Balibago",
            consent_given=True,
        )
        request_item = ServiceRequest.objects.create(
            scope="BARANGAY",
            farmer=None,
            target_barangay=self.farmer.barangay,
            service=self.service,
            subject=self.service.name,
            priority="MEDIUM",
            status="IN_PROGRESS",
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("interventions:create"),
            {"service_request": request_item.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["scope"], "BARANGAY")
        self.assertEqual(
            response.context["form"].initial["target_barangay"],
            self.farmer.barangay,
        )
        intervention = Intervention.objects.create(
            service_request=request_item,
            scope="BARANGAY",
            target_barangay=self.farmer.barangay,
            status="SCHEDULED",
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Barangay-wide seed distribution",
            recorded_by=self.staff,
        )

        from apps.interventions.services import complete_registered_request_intervention

        completed = complete_registered_request_intervention(request_item, self.staff)
        completed.refresh_from_db()
        self.assertEqual(completed.scope, "BARANGAY")
        self.assertEqual(completed.target_barangay, self.farmer.barangay)
        self.assertIsNone(completed.farmer)
        recipient_ids = set(
            completed.recipients.filter(is_active=True).values_list("farmer_id", flat=True)
        )
        self.assertEqual(recipient_ids, {self.farmer.pk, second_farmer.pk})
        self.assertNotIn(other_farmer.pk, recipient_ids)

    def test_barangay_intervention_lists_every_active_farmer_in_recipient_snapshot(self):
        second_farmer = Farmer.objects.create(
            first_name="Lorna",
            last_name="Reyes",
            barangay=self.farmer.barangay,
            consent_given=True,
        )
        other_farmer = Farmer.objects.create(
            first_name="Mario",
            last_name="Cruz",
            barangay="Balibago",
            consent_given=True,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("interventions:create"),
            {
                "scope": "BARANGAY",
                "target_barangay": self.farmer.barangay,
                "status": "SCHEDULED",
                "intervention_type": "SEEDS",
                "intervention_date": "2026-10-21",
                "description": "Barangay-wide seed distribution",
                "provider": "Office for Agricultural Services",
            },
        )

        self.assertRedirects(response, reverse("interventions:list"))
        intervention = Intervention.objects.latest("pk")
        recipient_ids = set(
            intervention.recipients.filter(is_active=True).values_list(
                "farmer_id", flat=True
            )
        )
        self.assertEqual(recipient_ids, {self.farmer.pk, second_farmer.pk})
        self.assertNotIn(other_farmer.pk, recipient_ids)

        detail = self.client.get(
            reverse("interventions:detail", args=[intervention.pk])
        )
        self.assertContains(detail, self.farmer.record_id)
        self.assertContains(detail, self.farmer.list_name)
        self.assertContains(detail, second_farmer.record_id)
        self.assertContains(detail, second_farmer.list_name)
        self.assertNotContains(detail, other_farmer.list_name)
        self.assertNotContains(detail, "No recipients recorded.")
        history = ActivityLog.objects.get(
            module="Interventions",
            target_label=intervention.reference_id,
            title="Intervention Recorded",
        )
        changed_fields = {change["field"] for change in history.details}
        self.assertIn("Recipients", changed_fields)
        self.assertIn("Intervention type", changed_fields)
        recipient_change = next(
            change for change in history.details if change["field"] == "Recipients"
        )
        self.assertIn(second_farmer.list_name, recipient_change["after"])

    def test_linked_barangay_intervention_rejects_a_different_barangay(self):
        request_item = ServiceRequest.objects.create(
            scope="BARANGAY",
            farmer=None,
            target_barangay="Alupay",
            service=self.service,
            subject=self.service.name,
            priority="MEDIUM",
            status="IN_PROGRESS",
            assigned_to=self.staff,
        )
        intervention = Intervention.objects.create(
            service_request=request_item,
            scope="BARANGAY",
            target_barangay="Alupay",
            status="SCHEDULED",
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Barangay-wide seed distribution",
            provider="Office for Agricultural Services",
            recorded_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("interventions:edit", args=[intervention.pk]),
            {
                "scope": "BARANGAY",
                "target_barangay": "Bagong Pook",
                "service_request": request_item.pk,
                "status": "SCHEDULED",
                "intervention_type": "SEEDS",
                "intervention_date": intervention.intervention_date.isoformat(),
                "description": intervention.description,
                "provider": intervention.provider,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Barangay must remain Alupay because it is set by the related service request.",
        )
        self.assertNotContains(response, f"{intervention.reference_id} was updated.")
        intervention.refresh_from_db()
        self.assertEqual(intervention.target_barangay, "Alupay")
        self.assertFalse(
            ActivityLog.objects.filter(
                module="Interventions",
                target_label=intervention.reference_id,
                title="Intervention Updated",
            ).exists()
        )

    def test_intervention_update_history_records_before_and_after_values(self):
        intervention = Intervention.objects.create(
            farmer=self.farmer,
            scope="INDIVIDUAL",
            status="SCHEDULED",
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Seed distribution scheduled",
            provider="Office for Agricultural Services",
            recorded_by=self.staff,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("interventions:edit", args=[intervention.pk]),
            {
                "scope": "INDIVIDUAL",
                "farmer": self.farmer.pk,
                "status": "ONGOING",
                "intervention_type": "SEEDS",
                "intervention_date": intervention.intervention_date.isoformat(),
                "description": "Seed distribution is ongoing",
                "provider": intervention.provider,
            },
        )

        self.assertRedirects(response, reverse("interventions:list"))
        history = ActivityLog.objects.get(
            module="Interventions",
            target_label=intervention.reference_id,
            title="Intervention Updated",
        )
        changes = {change["field"]: change for change in history.details}
        self.assertEqual(changes["Status"]["before"], "Scheduled")
        self.assertEqual(changes["Status"]["after"], "Ongoing")
        self.assertEqual(
            changes["Description"]["before"], "Seed distribution scheduled"
        )
        self.assertEqual(
            changes["Description"]["after"], "Seed distribution is ongoing"
        )

        history_page = self.client.get(
            reverse("interventions:history", args=[intervention.pk])
        )
        self.assertContains(history_page, "Seed distribution scheduled")
        self.assertContains(history_page, "Seed distribution is ongoing")

    def test_slip_b_is_separate_and_contains_official_parcel_workflow(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farmers:slip_b", args=[self.farmer.pk]))
        self.assertRedirects(
            response,
            reverse("farm_parcels:edit", args=[self.parcel.pk]),
        )
        parcel_form = self.client.get(reverse("farm_parcels:edit", args=[self.parcel.pk]))
        self.assertContains(parcel_form, "Update Farm Parcel Record")
        self.assertContains(parcel_form, "Use Update Record for verified parcel and land changes")
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
        self.assertContains(saved_detail, "Update record saved.")
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
        self.assertContains(history_page, "Farm Parcel Update Record History")
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
        self.assertContains(parcel_detail, 'name="field_photo"')
        self.assertNotContains(parcel_detail, 'name="field_photo" multiple')

        image_bytes = BytesIO()
        Image.new("RGB", (16, 16), "green").save(image_bytes, format="PNG")
        history_count = FarmerUpdateHistory.objects.filter(
            farmer=self.farmer, update_type="SLIP_B"
        ).count()
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("farm_parcels:photo_upload", args=[self.parcel.pk]),
                {
                    "field_photo": SimpleUploadedFile(
                        "field.png", image_bytes.getvalue(), content_type="image/png"
                    )
                },
            )
            self.assertRedirects(response, reverse("farm_parcels:detail", args=[self.parcel.pk]))
            photo = FarmParcelPhoto.objects.get(parcel=self.parcel)
            self.assertEqual(photo.uploaded_by, self.staff)
            self.assertTrue(photo.is_active)

            replacement_bytes = BytesIO()
            Image.new("RGB", (16, 16), "blue").save(replacement_bytes, format="PNG")
            replacement_response = self.client.post(
                reverse("farm_parcels:photo_upload", args=[self.parcel.pk]),
                {
                    "field_photo": SimpleUploadedFile(
                        "replacement.png",
                        replacement_bytes.getvalue(),
                        content_type="image/png",
                    )
                },
            )
            self.assertRedirects(
                replacement_response,
                reverse("farm_parcels:detail", args=[self.parcel.pk]),
            )
            photo.refresh_from_db()
            self.assertFalse(photo.is_active)
            self.assertEqual(
                FarmParcelPhoto.objects.filter(parcel=self.parcel, is_active=True).count(),
                1,
            )
        self.assertEqual(
            FarmerUpdateHistory.objects.filter(
                farmer=self.farmer, update_type="SLIP_B"
            ).count(),
            history_count,
        )
        self.assertTrue(
            ActivityLog.objects.filter(title="Farm Parcel Photo Replaced").exists()
        )

    def test_cancelled_service_request_has_actions_and_can_be_restored(self):
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
        self.assertEqual(edit_response.status_code, 200)
        detail = self.client.get(reverse("service_requests:detail", args=[request_item.pk]))
        self.assertContains(detail, "Update Service Request")
        detail_html = detail.content.decode()
        self.assertIn(f"<h2>{request_item.beneficiary_label}</h2>", detail_html)
        self.assertIn(f"<p>{request_item.service.name}</p>", detail_html)
        listing = self.client.get(reverse("service_requests:list"), {"status": "CANCELLED"})
        self.assertContains(listing, f'Edit {request_item.request_id}')
        self.assertContains(listing, f'Restore {request_item.request_id}')
        intervention = self.client.get(
            reverse("interventions:create"), {"service_request": request_item.pk}
        )
        self.assertRedirects(
            intervention,
            reverse("service_requests:detail", args=[request_item.pk]),
        )
        restored = self.client.post(
            reverse("service_requests:delete", args=[request_item.pk]),
            {"action": "restore"},
        )
        self.assertRedirects(restored, reverse("service_requests:list"))
        request_item.refresh_from_db()
        self.assertEqual(request_item.status, "PENDING")
        self.assertTrue(
            request_item.history.filter(
                action="REOPENED", from_status="CANCELLED", to_status="PENDING"
            ).exists()
        )

    def test_parcel_table_hides_rsbsa_column_and_map_can_focus_saved_parcel(self):
        self.client.force_login(self.staff)
        parcel_list = self.client.get(reverse("farm_parcels:list"))
        self.assertEqual(parcel_list.status_code, 200)
        self.assertNotContains(parcel_list, "RSBSA Record")
        self.assertNotContains(parcel_list, '<select name="crop_type"', html=False)
        self.assertNotContains(parcel_list, "<th>Crop</th>", html=False)
        self.assertContains(parcel_list, "<th>Actions</th>", html=False)
        self.assertContains(parcel_list, reverse("farm_parcels:edit", args=[self.parcel.pk]))
        self.assertContains(parcel_list, reverse("farm_parcels:delete", args=[self.parcel.pk]))
        self.assertContains(parcel_list, ":nth-child(9){width:8%!important}")

        self.parcel.coordinates = "13.8467000, 121.2060000"
        self.parcel.save(update_fields=["coordinates"])
        map_response = self.client.get(reverse("farm_parcels:map"))
        self.assertEqual(map_response.status_code, 200)
        self.assertEqual(map_response.context["mapped_count"], 1)
        self.assertEqual(map_response.context["map_markers"][0]["id"], self.parcel.pk)
        self.assertEqual(map_response.context["map_markers"][0]["barangay"], "Bulihan")
        self.assertEqual(map_response.context["map_markers"][0]["crops"][0]["name"], "Rice")
        self.assertContains(map_response, 'id="mapBarangayFilter"')
        self.assertContains(map_response, 'id="mapCommodityFilter"')
        self.assertContains(map_response, "applyMapFilters")
        self.assertContains(map_response, "markerByFarmer")
        self.assertContains(map_response, "Parcel Already Pinned")
        self.assertContains(map_response, "farmerMarker.openPopup()")
        self.assertNotContains(map_response, 'name="map_layer"')
        self.assertNotContains(map_response, "Terrain with place names")
        self.assertNotContains(map_response, "Street map with place names")
        self.assertContains(map_response, "World_Imagery")
        self.assertContains(map_response, "maxBounds: rosarioBounds")
        self.assertContains(map_response, "keepInView: true")

    def test_newest_parcel_is_first_and_named_in_the_farm_parcel_table(self):
        newest = FarmParcel.objects.create(
            farmer=self.farmer,
            parcel_name="Newest Registered Field",
            barangay="Bulihan",
            area_hectares=Decimal("1.25"),
            ownership_type="OWNED",
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("farm_parcels:list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object_list"][0], newest)
        self.assertContains(response, newest.display_name)
        self.assertEqual(newest.display_name, f"P-{newest.pk:04d}")

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
        self.assertContains(map_response, "Remove pin")
        self.assertContains(map_response, "Save New Location")

    def test_staff_can_remove_parcel_pin_and_change_is_audited(self):
        self.parcel.coordinates = "13.8467000, 121.2060000"
        self.parcel.save(update_fields=["coordinates"])
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("farm_parcels:pin_farmer"),
            {"parcel_id": self.parcel.pk, "operation": "remove"},
        )
        self.assertEqual(response.status_code, 200)
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.coordinates, "")
        activity = ActivityLog.objects.get(
            title="Farm Parcel Map Pin Removed",
            target_label=f"{self.farmer.record_id} - {self.parcel.display_name}",
        )
        self.assertEqual(activity.details[0]["after"], "Not pinned")

    def test_parcel_form_is_land_only_and_crops_are_managed_separately(self):
        self.client.force_login(self.staff)
        create_url = reverse("farm_parcels:create")
        response = self.client.get(create_url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].fields["georef_id"].required)
        self.assertNotIn("crop_formset", response.context)
        self.assertNotContains(response, "Add Crop")
        self.assertContains(response, "Add commodities separately in Commodity Management")

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
                "cropping_start_month": "January",
                "cropping_end_month": "March",
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

    def test_staff_accomplishment_report_groups_requests_by_staff_and_commodity(self):
        request_record = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject="Rice seed request",
            status="COMPLETED",
            assigned_to=self.staff,
        )
        ServiceRequestHistory.objects.create(
            service_request=request_record,
            actor=self.staff,
            action="UPDATED",
            from_status="IN_PROGRESS",
            to_status="COMPLETED",
        )

        title, headers, rows = build_system_report(
            "staff_accomplishment", "month", {"staff": str(self.staff.pk)}
        )

        self.assertEqual(title, "Staff Activity & Accomplishment Report")
        self.assertIn("Commodity", headers)
        service_row = next(row for row in rows if row[1] == "Service Requests")
        self.assertEqual(service_row[0], self.staff.display_name)
        self.assertEqual(service_row[2], "Seed Assistance")
        self.assertEqual(service_row[3], "Rice")
        self.assertEqual(service_row[4:6], [1, 1])

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

        other_farmer = Farmer.objects.create(
            first_name="Mario",
            last_name="Reyes",
            barangay="Balibago",
            consent_given=True,
        )
        intervention.recipients.create(farmer=other_farmer, status="RECEIVED")
        _title, _headers, barangay_rows = build_report(
            "intervention_registry",
            "all",
            {"barangay": self.farmer.barangay},
        )
        self.assertEqual(len(barangay_rows), 1)
        self.assertEqual(barangay_rows[0][4], self.farmer.barangay)

        self.client.force_login(self.staff)
        reports = self.client.get(
            reverse("reports:home"),
            {"report_type": "intervention_registry", "date_range": "all"},
        )
        self.assertContains(reports, "Complete Intervention Register")
        self.assertContains(reports, intervention.reference_id)
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertContains(dashboard, "Intervention Delivery")
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
        for header in ("Beneficiary", "Barangay", "Request Type", "Request", "Date Requested"):
            self.assertIn(header, headers)
        row = next(item for item in rows if item[0] == request_item.request_id)
        self.assertEqual(row[2], self.farmer.list_name)
        self.assertEqual(row[3], self.farmer.barangay)
        self.assertEqual(row[5], request_item.subject)

    def test_farmer_master_list_orders_newest_records_first(self):
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
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_operational_record_tables_show_newest_entries_first(self):
        newest_farmer = Farmer.objects.create(
            first_name="Latest",
            last_name="Record",
            barangay="Bulihan",
            consent_given=True,
        )
        newest_parcel = FarmParcel.objects.create(
            farmer=newest_farmer,
            barangay="Bulihan",
            area_hectares=Decimal("1.00"),
            ownership_type="OWNED",
        )
        newest_crop = CropRecord.objects.create(
            parcel=newest_parcel,
            crop_type="Coffee",
            area_hectares=Decimal("1.00"),
        )
        newest_request = ServiceRequest.objects.create(
            farmer=newest_farmer,
            service=self.service,
            subject=self.service.name,
            status="PENDING",
        )
        newest_intervention = Intervention.objects.create(
            farmer=newest_farmer,
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Latest delivered assistance",
        )

        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("farmers:list")).context["object_list"][0],
            newest_farmer,
        )
        self.assertEqual(
            self.client.get(reverse("farm_parcels:list")).context["object_list"][0],
            newest_parcel,
        )
        crop_response = self.client.get(reverse("crops:list"))
        listed_farmer = crop_response.context["object_list"][0]
        self.assertEqual(listed_farmer, newest_farmer)
        self.assertEqual(listed_farmer.listed_crop_records[0], newest_crop)
        self.assertEqual(
            self.client.get(reverse("service_requests:list")).context["object_list"][0],
            newest_request,
        )
        self.assertEqual(
            self.client.get(reverse("interventions:list")).context["object_list"][0],
            newest_intervention,
        )

        self.client.force_login(self.admin)
        newest_account = get_user_model().objects.create_user(
            username="newest-account",
            password="StrongPass123!",
            role="STAFF",
        )
        self.assertEqual(
            self.client.get(reverse("accounts:list")).context["object_list"][0],
            newest_account,
        )

    def test_reports_start_with_choose_report_and_show_only_relevant_filters(self):
        self.client.force_login(self.staff)
        initial = self.client.get(reverse("reports:home"))
        self.assertEqual(initial.context["selected_report_type"], "")
        self.assertContains(initial, '<option value="">Choose a report</option>', html=True)
        self.assertContains(initial, 'data-filter-row="common" hidden')
        self.assertNotContains(initial, "Summarizes service requests by status")

        service_report = self.client.get(
            reverse("reports:home"),
            {
                "report_type": "service_status",
                "date_range": "all",
                "commodity": "Coffee",
            },
        )
        self.assertContains(service_report, 'data-filter-row="status"')
        self.assertNotContains(service_report, 'data-filter-row="status" hidden')
        self.assertContains(service_report, 'data-filter-row="intervention" hidden')
        self.assertContains(service_report, 'data-filter-row="commodity" hidden')
        self.assertEqual(service_report.context["selected_filters"]["commodity"], "")

        intervention_report = self.client.get(
            reverse("reports:home"),
            {"report_type": "intervention_registry", "date_range": "all"},
        )
        self.assertContains(intervention_report, 'data-filter-row="intervention"')
        self.assertNotContains(intervention_report, 'data-filter-row="intervention" hidden')
        self.assertContains(intervention_report, 'data-filter-row="status" hidden')
        self.assertContains(intervention_report, 'data-filter-row="commodity" hidden')

        farmer_report = self.client.get(
            reverse("reports:home"),
            {"report_type": "farmer_master", "date_range": "all"},
        )
        self.assertContains(farmer_report, 'data-filter-row="commodity"')
        self.assertNotContains(farmer_report, 'data-filter-row="commodity" hidden')

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
        self.assertContains(response, "Commodity Production Summary")
        self.assertContains(response, "Applied report filters")
        self.assertContains(response, "Commodity:</b> Rice", html=False)

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
                "Commodities",
            ],
        )
        self.assertEqual(preview["rows"][0][0], self.farmer.record_id)
        self.assertEqual(preview["rows"][0][1], self.farmer.full_name)
        self.assertEqual(preview["rows"][0][8], "Rice")
        self.assertContains(response, "farmer-master-preview")
        self.assertNotContains(response, "Farmer Master List chart")

    def test_farm_reports_show_the_commodity_used_to_filter_each_row(self):
        for report_type in ("farm_area_by_barangay", "farmers_by_ownership"):
            _title, headers, rows = build_report(
                report_type,
                "all",
                {"commodity": "Rice"},
            )
            commodity_index = headers.index("Commodities")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][commodity_index], "Rice")

    def test_irrelevant_commodity_filter_does_not_change_service_request_report(self):
        request_item = ServiceRequest.objects.create(
            farmer=self.farmer,
            service=self.service,
            subject=self.service.name,
            status="PENDING",
        )

        _title, headers, rows = build_report(
            "service_status",
            "all",
            {"commodity": "Coffee", "status": "PENDING"},
        )

        self.assertNotIn("Commodity", headers)
        self.assertIn(request_item.request_id, {row[0] for row in rows})

    def test_staff_dashboard_shows_scoped_analytics_and_fixed_weather_location(self):
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
        self.assertNotIn("planting_date", attention)
        self.assertEqual(response.context["attention_priority"]["key"], "mapping")
        self.assertEqual(response.context["area_planted"], Decimal("2.00"))
        self.assertEqual(response.context["managed_land_area"], Decimal("2.50"))
        self.assertEqual(response.context["data_completeness_score"], 67)
        self.assertEqual(response.context["commodity_breakdown"][0]["label"], "Rice")
        self.assertEqual(response.context["commodity_breakdown"][0]["records"], 1)
        self.assertEqual(response.context["commodity_breakdown"][0]["share"], 100)
        self.assertEqual(response.context["barangay_distribution"][0]["barangay"], "Bulihan")
        self.assertEqual(response.context["barangay_distribution"][0]["share"], 100)
        self.assertEqual(response.context["most_requested_services"][0]["service__name"], "Seed Assistance")
        self.assertNotIn("farmer_statistics", response.context)
        self.assertNotContains(response, "Farmer Statistics")
        self.assertContains(response, "Rosario, Batangas")
        self.assertContains(response, 'data-latitude="13.8442"')
        self.assertNotContains(response, "ROSARIO AGRICULTURAL OPERATIONS")
        self.assertNotContains(response, "Staff Overview")
        self.assertNotContains(response, "Records, workload, and priorities at a glance.")
        self.assertNotContains(response, "Current system overview")
        self.assertContains(response, "Active farmers")
        self.assertContains(response, "Production Snapshot")
        self.assertContains(response, "Commodity Mix")
        self.assertContains(response, "Where Farmers Are Registered")
        self.assertNotContains(response, "Records Needing Attention")
        self.assertContains(response, "Service &amp; Intervention Workload")
        self.assertContains(response, "Request Pipeline")
        self.assertContains(response, "Intervention Delivery")
        self.assertNotContains(response, "Most Requested Services")
        self.assertNotContains(response, "Continue Your Work")
        self.assertContains(response, 'class="commodity-donut"')
        self.assertContains(response, 'class="barangay-coverage-list"')
        self.assertNotContains(response, 'class="commodity-horizontal-chart"')
        self.assertNotContains(response, "Six-Month Operational Trend")
        self.assertNotContains(response, "Parcels without map pins")
        self.assertNotContains(response, 'data-card-url="/crops/"')
        self.assertNotContains(response, "View crop records")
        self.assertNotContains(response, "SUGGESTED CROP")
        self.assertNotContains(response, "Data reference")
        self.assertContains(response, 'class="staff-operations-weather-grid"')
        self.assertContains(response, "Wet season")
        self.assertNotContains(response, "Local FMIS data")
        self.assertNotContains(response, "Planning aid only")
        self.assertNotContains(response, "confidence")
        self.assertEqual(response.context["crop_recommendation"]["crop"], "Rice")
        self.assertEqual(response.context["crop_recommendation"]["confidence"], "Low")
        page = response.content.decode()
        self.assertLess(page.index("Active farmers"), page.index("Production Snapshot"))
        self.assertLess(page.index("Production Snapshot"), page.index("Service &amp; Intervention Workload"))
        self.assertLess(page.index("Rosario Weather"), page.index("Planning reference"))
        self.assertNotContains(response, "Inventor")
        self.assertNotContains(response, "Pending Projects")
        self.assertNotContains(response, "Requests by Service")

    def test_staff_dashboard_reads_all_active_saved_records_from_the_database(self):
        # Older imports and user-entered records may contain harmless spacing in
        # fixed location fields. They are still FMIS records and must be counted.
        self.farmer.city_municipality = "Rosario "
        self.farmer.province = "Batangas "
        self.farmer.save(update_fields=["city_municipality", "province"])
        self.parcel.municipality = "Rosario "
        self.parcel.province = "Batangas "
        self.parcel.save(update_fields=["municipality", "province"])

        inactive_parcel = FarmParcel.objects.create(
            farmer=self.farmer,
            barangay="Bulihan",
            municipality="Rosario",
            province="Batangas",
            area_hectares=Decimal("0.75"),
            ownership_type="OWNED",
            land_type="UPLAND",
            farm_type="Rainfed",
            is_active=False,
        )
        CropRecord.objects.create(
            parcel=inactive_parcel,
            crop_type="Coffee",
            area_hectares=Decimal("0.50"),
            is_active=True,
        )

        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard:staff_home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["farmers"], 1)
        self.assertEqual(response.context["parcels"], 2)
        self.assertEqual(response.context["crops"], 2)
        self.assertEqual(response.context["managed_land_area"], Decimal("3.25"))
        self.assertEqual(
            {item["label"] for item in response.context["commodity_breakdown"]},
            {"Rice", "Coffee"},
        )

        parcel_list = self.client.get(reverse("farm_parcels:list"))
        listed_parcels = list(parcel_list.context["object_list"])
        self.assertEqual(
            [parcel.pk for parcel in listed_parcels],
            sorted((parcel.pk for parcel in listed_parcels), reverse=True),
        )
        self.assertIn(inactive_parcel, listed_parcels)

    def test_staff_dashboard_lists_every_commodity_and_barangay_without_other_bucket(self):
        commodity_names = ["Coffee", "Banana", "Corn", "Coconut", "Cacao"]
        for name in commodity_names:
            CropRecord.objects.create(
                parcel=self.parcel,
                crop_type=name,
                area_hectares=Decimal("0.10"),
            )
        barangays = ["Alupay", "Antipolo", "Bagong Pook", "Balibago", "Bayawang"]
        for index, barangay in enumerate(barangays):
            Farmer.objects.create(
                first_name=f"Farmer{index}",
                last_name="Coverage",
                barangay=barangay,
                consent_given=True,
            )

        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard:staff_home"))

        labels = {item["label"] for item in response.context["commodity_breakdown"]}
        self.assertEqual(labels, {"Rice", *commodity_names})
        self.assertNotIn("Other commodities", labels)
        shown_barangays = {
            item["barangay"] for item in response.context["barangay_distribution"]
        }
        self.assertEqual(shown_barangays, {"Bulihan", *barangays})
        self.assertContains(response, "All barangays")
        self.assertContains(response, "Coffee")

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
        self.assertContains(admin_reports, "data-download-form", count=4)
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
        self.assertIn("20 commodity record(s)", locally_supported["evidence"])

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
            # Close only the streamed file. HttpResponse.close() emits
            # request_finished, which closes the MySQL connection that
            # Django's TestCase intentionally keeps inside an atomic block.
            for closer in response._resource_closers:
                closer()
            response._resource_closers.clear()

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
            reverse("farmers:list"),
        )

        self.client.force_login(recipient)
        dashboard = self.client.get(reverse("dashboard:staff_home"))
        self.assertContains(dashboard, "notification-count")
        self.assertContains(dashboard, notification.title)
        self.assertEqual(dashboard.context["notification_unread_count"], 1)

        notification.url = (
            f"{reverse('activity_logs:list')}?highlight={activity.pk}#activity-{activity.pk}"
        )
        notification.save(update_fields=("url",))
        notification_page = self.client.get(reverse("notifications:list"))
        self.assertEqual(notification_page.status_code, 200)
        self.assertContains(notification_page, notification.title)

        opened = self.client.post(
            reverse("notifications:open", args=[notification.pk]), follow=True
        )
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.redirect_chain[-1][0], reverse("farmers:list"))
        self.assertNotContains(opened, "available to administrators only")
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

    def test_notifications_are_separated_by_admin_and_staff_audience(self):
        from apps.activity_logs.services import record_event
        from apps.notifications.models import Notification

        intervention_activity = record_event(
            actor=self.admin,
            title="Intervention Recorded",
            module="Interventions",
            description="An intervention was recorded.",
            path="/interventions/new/",
            target_label="INT-TEST",
        )
        self.assertTrue(
            Notification.objects.filter(
                source_activity=intervention_activity,
                recipient=self.staff,
                url=reverse("interventions:list"),
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                source_activity=intervention_activity,
                recipient=self.admin,
            ).exists()
        )

        account_activity = record_event(
            actor=self.staff,
            title="User Account Updated",
            module="User Accounts",
            description="A user account was updated.",
            path="/accounts/1/edit/",
            target_label="Account test",
        )
        self.assertTrue(
            Notification.objects.filter(
                source_activity=account_activity,
                recipient=self.admin,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                source_activity=account_activity,
                recipient=self.staff,
            ).exists()
        )

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
        self.assertTrue(notification.url.startswith(reverse("activity_logs:list")))

        self.client.force_login(self.admin)
        notification_page = self.client.get(reverse("notifications:list"))
        self.assertEqual(notification_page.status_code, 200)
        self.assertContains(notification_page, notification.title)
        opened = self.client.post(
            reverse("notifications:open", args=[notification.pk]), follow=True
        )
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.redirect_chain[-1][0], notification.url)

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
            protected_photo_url = reverse("settings_page:profile_photo")
            self.assertContains(settings_page, protected_photo_url)
            self.assertContains(settings_page, "Remove photo")
            protected_photo = self.client.get(protected_photo_url)
            self.assertEqual(protected_photo.status_code, 200)
            protected_photo.close()
            self.client.logout()
            self.assertEqual(self.client.get(protected_photo_url).status_code, 302)
            self.client.force_login(self.staff)

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

    def test_wsgi_startup_prewarm_uses_secure_landing_request(self):
        observed = {}

        def application(environ, start_response):
            observed.update(environ)
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"ready"]

        status = prewarm_wsgi_application(application, host="fmis.example.gov.ph")

        self.assertEqual(status, 200)
        self.assertEqual(observed["REQUEST_METHOD"], "GET")
        self.assertEqual(observed["PATH_INFO"], "/")
        self.assertEqual(observed["HTTP_HOST"], "fmis.example.gov.ph")
        self.assertEqual(observed["wsgi.url_scheme"], "https")

    def test_wsgi_startup_prewarm_rejects_failed_readiness(self):
        def application(environ, start_response):
            start_response("500 Internal Server Error", [])
            return [b"failed"]

        with self.assertRaisesRegex(RuntimeError, "HTTP 500"):
            prewarm_wsgi_application(application)

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

            recovery_dir = Path(temp_dir) / "recovery-drill"
            call_command(
                "prepare_fmis_recovery",
                str(backups[0]),
                str(recovery_dir),
                verbosity=0,
            )
            self.assertTrue((recovery_dir / "manifest.json").is_file())
            self.assertTrue((recovery_dir / "database" / "database.json").is_file())

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

    def test_rclone_backup_upload_verifies_remote_size(self):
        from apps.common.backups import _upload_and_verify

        with tempfile.TemporaryDirectory() as temp_dir:
            archive = Path(temp_dir) / "fmis-backup-test.fmisbak"
            archive.write_bytes(b"encrypted-backup")
            completed = Mock(returncode=0, stdout="")
            verified = Mock(
                returncode=0,
                stdout=json.dumps({"count": 1, "bytes": archive.stat().st_size}),
            )
            with override_settings(
                BACKUP_AZURE_CONTAINER_URL="",
                BACKUP_RCLONE_REMOTE="gdrive:fmis-production",
                RCLONE_PATH="/usr/bin/rclone",
            ), patch("apps.common.backups.Path.is_file", return_value=True), patch(
                "apps.common.backups.subprocess.run",
                side_effect=[completed, verified],
            ) as run:
                self.assertTrue(_upload_and_verify(archive, "a" * 64))
            self.assertEqual(run.call_args_list[0].args[0][1], "copyto")
            self.assertEqual(
                run.call_args_list[0].args[0][-1],
                "gdrive:fmis-production/fmis-backup-test.fmisbak",
            )
            self.assertEqual(run.call_args_list[1].args[0][1], "size")
