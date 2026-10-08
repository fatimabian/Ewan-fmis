from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.authentication.models import CustomUser
from apps.farmers.models import Farmer

from .models import Intervention, InterventionRecipient


class InterventionModuleTests(TestCase):
    def setUp(self):
        self.staff = CustomUser.objects.create_user(
            username="interventionstaff",
            password="ValidPass123!",
            role="STAFF",
            is_active=True,
        )
        self.admin = CustomUser.objects.create_user(
            username="interventionadmin",
            password="ValidPass123!",
            role="ADMIN",
            is_active=True,
        )
        self.farmer = Farmer.objects.create(
            first_name="Maria",
            last_name="Santos",
            barangay="Alupay",
            consent_given=True,
        )

    def test_staff_can_record_filter_and_archive_an_intervention(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("interventions:create"), {
            "farmer": self.farmer.pk,
            "intervention_type": "SEEDS",
            "intervention_date": date.today().isoformat(),
            "description": "Certified rice seed distribution",
            "quantity": "10.00",
            "unit": "kg",
            "provider": "Office for Agricultural Services",
            "is_active": "on",
        })
        self.assertRedirects(response, reverse("interventions:list"))
        intervention = Intervention.objects.get()
        self.assertEqual(intervention.recorded_by, self.staff)
        listing = self.client.get(reverse("interventions:list"), {"q": intervention.reference_id})
        self.assertContains(listing, "Seeds / planting materials")
        self.assertNotContains(listing, "Certified rice seed distribution")
        self.client.post(reverse("interventions:archive", args=[intervention.pk]))
        intervention.refresh_from_db()
        self.assertFalse(intervention.is_active)
        archived = self.client.get(reverse("interventions:list"), {"status": "archived"})
        self.assertContains(archived, intervention.reference_id)

    def test_active_status_is_managed_only_by_archive_actions(self):
        from .forms import InterventionForm

        self.assertNotIn("is_active", InterventionForm().fields)

    def test_selected_farmer_intervention_saves_a_fixed_recipient_snapshot(self):
        second_farmer = Farmer.objects.create(
            first_name="Jose", last_name="Reyes", barangay="Alupay", consent_given=True
        )
        self.client.force_login(self.staff)
        response = self.client.post(reverse("interventions:create"), {
            "scope": "SELECTED",
            "selected_farmers": [self.farmer.pk, second_farmer.pk],
            "status": "SCHEDULED",
            "intervention_type": "TRAINING",
            "intervention_date": date.today().isoformat(),
            "description": "Barangay farm safety seminar",
            "provider": "Office for Agricultural Services",
        })
        self.assertRedirects(response, reverse("interventions:list"))
        intervention = Intervention.objects.get()
        self.assertIsNone(intervention.farmer)
        self.assertEqual(intervention.scope, "SELECTED")
        self.assertEqual(intervention.recipients.filter(is_active=True).count(), 2)
        self.assertEqual(
            set(InterventionRecipient.objects.values_list("status", flat=True)),
            {"PENDING"},
        )

    def test_admin_is_kept_out_of_operational_intervention_pages(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("interventions:list"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))
