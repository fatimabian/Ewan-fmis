from datetime import date
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from apps.authentication.models import CustomUser
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest
from apps.service_catalog.models import ServiceCatalog

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
            "status": "COMPLETED",
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

    def test_list_filters_by_workflow_status(self):
        self.client.force_login(self.staff)
        scheduled = Intervention.objects.create(
            farmer=self.farmer,
            status="SCHEDULED",
            intervention_type="TRAINING",
            intervention_date=date.today(),
            description="Scheduled seminar",
        )
        completed = Intervention.objects.create(
            farmer=self.farmer,
            status="COMPLETED",
            intervention_type="SEEDS",
            intervention_date=date.today(),
            description="Completed distribution",
        )

        response = self.client.get(reverse("interventions:list"), {"status": "SCHEDULED"})

        self.assertContains(response, scheduled.reference_id)
        self.assertNotContains(response, completed.reference_id)
        self.assertContains(response, "Draft")
        self.assertContains(response, "Scheduled")
        self.assertContains(response, "Ongoing")
        self.assertContains(response, "Completed")
        self.assertContains(response, "Cancelled")

    def test_active_status_is_managed_only_by_archive_actions(self):
        from .forms import InterventionForm

        form = InterventionForm()
        self.assertNotIn("is_active", form.fields)
        self.assertEqual(form.initial["status"], "")
        self.assertTrue(form.fields["status"].required)

    def test_create_form_has_searchable_farmer_selection_without_snapshot_notice(self):
        Farmer.objects.create(
            first_name="Unloaded", last_name="Farmer", barangay="Alupay", consent_given=True
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("interventions:create"))
        self.assertContains(
            response,
            "Search by Farmer ID, RSBSA number, name, or barangay",
        )
        self.assertNotContains(
            response,
            "The recipient list is saved as a fixed snapshot",
        )
        self.assertNotContains(response, "Unloaded, Farmer")
        self.assertContains(response, "N/A — no related service request")
        page = response.content.decode()
        self.assertLess(page.index('name="service_request"'), page.index('name="scope"'))

        search = self.client.get(reverse("interventions:farmer_search"), {"q": "Unloaded"})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(len(search.json()["results"]), 1)
        self.assertIn("Farmer, Unloaded", search.json()["results"][0]["label"])

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

    def test_association_request_creates_fixed_member_recipient_snapshot(self):
        self.farmer.is_association_member = True
        self.farmer.fca_membership = "Hog Raisers Association"
        self.farmer.save(update_fields=["is_association_member", "fca_membership"])
        second = Farmer.objects.create(
            first_name="Pedro",
            last_name="Reyes",
            barangay="Bagong Pook",
            consent_given=True,
            is_association_member=True,
            fca_membership="Hog Raisers Association",
        )
        Farmer.objects.create(
            first_name="Other",
            last_name="Association",
            barangay="Alupay",
            is_association_member=True,
            fca_membership="Mufai",
        )
        service, _ = ServiceCatalog.objects.get_or_create(
            code="SEED",
            defaults={
                "name": "Seed Assistance",
                "category": "Farm Inputs",
                "description": "Seed support",
                "processing_time": "Depends on assessment",
            },
        )
        request = ServiceRequest.objects.create(
            scope="ASSOCIATION",
            target_association="Hog Raisers Association",
            farmer=None,
            service=service,
            subject=service.name,
            status="PENDING",
            assigned_to=self.staff,
        )
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("interventions:create"),
            {
                "service_request": request.pk,
                "scope": "ASSOCIATION",
                "target_association": "Hog Raisers Association",
                "status": "SCHEDULED",
                "intervention_type": "SEEDS",
                "intervention_date": date.today().isoformat(),
                "description": "Association seed distribution",
                "provider": "Office for Agricultural Services",
            },
        )
        self.assertRedirects(response, reverse("interventions:list"))
        intervention = Intervention.objects.get(service_request=request)
        self.assertEqual(intervention.scope, "ASSOCIATION")
        self.assertEqual(intervention.target_association, "Hog Raisers Association")
        self.assertEqual(
            set(
                intervention.recipients.filter(is_active=True).values_list(
                    "farmer_id", flat=True
                )
            ),
            {self.farmer.pk, second.pk},
        )

    def test_demo_farmer_commands_are_repeatable_and_safely_removable(self):
        Farmer.objects.create(
            first_name="Demo0001",
            middle_name="Sample",
            last_name="Farmer0001",
            barangay="Alupay",
            rsbsa_number="DEMO-RSBSA-000001",
            registration_status="COMPLETED",
            consent_given=True,
        )
        call_command("seed_demo_farmers", count=12, stdout=StringIO())
        call_command("seed_demo_farmers", count=12, stdout=StringIO())
        demo_farmers = Farmer.objects.filter(remarks__startswith="FMIS-DEMO-DATA:")
        self.assertEqual(demo_farmers.count(), 12)
        self.assertFalse(demo_farmers.filter(first_name__startswith="Demo").exists())
        self.assertEqual(
            set(demo_farmers.values_list("registration_status", flat=True)),
            {"COMPLETED", "SUBMITTED", "ENCODED", "SKIPPED"},
        )
        self.assertEqual(FarmParcel.objects.filter(farmer__in=demo_farmers).count(), 12)
        coordinates = list(
            FarmParcel.objects.filter(farmer__in=demo_farmers)
            .order_by("id")
            .values_list("coordinates", flat=True)
        )
        self.assertEqual(coordinates, [""] * 12)
        self.assertFalse(
            demo_farmers.exclude(location_coordinates="").exists(),
            "Synthetic records must not be assigned invented farm locations.",
        )
        self.assertEqual(CropRecord.objects.filter(parcel__farmer__in=demo_farmers).count(), 12)
        self.assertEqual(ServiceRequest.objects.filter(farmer__in=demo_farmers).count(), 4)
        self.assertEqual(Intervention.objects.filter(farmer__in=demo_farmers).count(), 3)
        with self.assertRaises(CommandError):
            call_command("delete_demo_farmers", stdout=StringIO())

        call_command(
            "delete_demo_farmers",
            confirm="DELETE-DEMO-FARMERS",
            stdout=StringIO(),
        )

        self.assertFalse(Farmer.objects.filter(remarks__startswith="FMIS-DEMO-DATA:").exists())
        self.assertTrue(Farmer.objects.filter(pk=self.farmer.pk).exists())
