from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from apps.farmers.models import Farmer
from apps.notifications.models import Notification
from apps.reports.export import build_report
from apps.service_catalog.models import ServiceCatalog

from .models import ServiceLevelPolicy, ServiceRequest, ServiceRequestEscalation, ServiceRequestHistory
from .forms import ServiceRequestForm
from .services import ensure_service_level_policies, service_effectiveness_metrics


class ServiceManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            username="service-staff", password="test-pass", role="STAFF", is_active=True
        )
        self.admin = user_model.objects.create_user(
            username="service-admin", password="test-pass", role="ADMIN", is_active=True
        )
        self.farmer = Farmer.objects.create(
            first_name="Test", last_name="Farmer", barangay="Alupay"
        )
        self.service, _ = ServiceCatalog.objects.get_or_create(
            code="SEED",
            defaults={
                "name": "Seed Assistance",
                "category": "Farm Inputs",
                "description": "Controlled test service",
                "processing_time": "Depends on assessment",
            },
        )
        ensure_service_level_policies()

    def request(self, **values):
        defaults = {
            "farmer": self.farmer,
            "service": self.service,
            "priority": "HIGH",
            "status": "PENDING",
            "assigned_to": self.staff,
        }
        defaults.update(values)
        return ServiceRequest.objects.create(**defaults)

    def test_proposed_priority_windows_create_separate_deadlines(self):
        expected = {"HIGH": (24, 72), "MEDIUM": (72, 96), "LOW": (120, 168)}
        for priority, hours in expected.items():
            with self.subTest(priority=priority):
                item = self.request(priority=priority)
                self.assertEqual(
                    item.first_response_due_at - item.created_at, timedelta(hours=hours[0])
                )
                self.assertEqual(item.due_at - item.created_at, timedelta(hours=hours[1]))
                self.assertFalse(ServiceLevelPolicy.objects.get(priority=priority).is_approved)

    def test_overdue_is_separate_from_workflow_status_and_explains_age(self):
        item = self.request(status="IN_PROGRESS")
        ServiceRequest.objects.filter(pk=item.pk).update(
            first_responded_at=timezone.now() - timedelta(days=5),
            due_at=timezone.now() - timedelta(days=4, hours=1),
        )
        item.refresh_from_db()
        self.assertEqual(item.status, "IN_PROGRESS")
        self.assertEqual(item.timing_indicator, "Overdue")
        self.assertIn("4 days overdue", item.overdue_text)
        self.assertIn("completion", item.overdue_text)

    def test_first_response_is_recorded_once(self):
        item = self.request()
        self.assertIsNone(item.first_responded_at)
        item.status = "IN_PROGRESS"
        item.save()
        first = item.first_responded_at
        item.notes = "Later edit"
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.first_responded_at, first)

    def test_completion_and_reopen_timestamps(self):
        item = self.request(status="IN_PROGRESS")
        item.status = "COMPLETED"
        item.save()
        self.assertIsNotNone(item.completed_at)
        item.status = "IN_PROGRESS"
        item.save()
        self.assertIsNone(item.completed_at)

    def test_escalation_command_is_idempotent(self):
        item = self.request()
        ServiceRequest.objects.filter(pk=item.pk).update(
            first_response_due_at=timezone.now() - timedelta(days=1)
        )
        call_command("process_service_escalations")
        call_command("process_service_escalations")
        self.assertEqual(ServiceRequestEscalation.objects.filter(service_request=item).count(), 1)
        self.assertEqual(
            ServiceRequestHistory.objects.filter(service_request=item, action="ESCALATED").count(), 1
        )
        self.assertEqual(Notification.objects.filter(title=f"{item.request_id} is overdue").count(), 2)

    def test_closed_requests_are_not_escalated(self):
        item = self.request(status="COMPLETED")
        ServiceRequest.objects.filter(pk=item.pk).update(
            first_response_due_at=timezone.now() - timedelta(days=2),
            due_at=timezone.now() - timedelta(days=1),
        )
        call_command("process_service_escalations")
        self.assertFalse(ServiceRequestEscalation.objects.filter(service_request=item).exists())

    def test_metrics_use_recorded_timestamps_and_cohort_resolution_rate(self):
        now = timezone.now()
        completed = self.request(status="PENDING")
        open_item = self.request(status="PENDING")
        ServiceRequest.objects.filter(pk=completed.pk).update(
            created_at=now - timedelta(days=2),
            first_responded_at=now - timedelta(days=2) + timedelta(hours=4),
            completed_at=now - timedelta(days=1),
            status="COMPLETED",
        )
        ServiceRequest.objects.filter(pk=open_item.pk).update(created_at=now - timedelta(hours=12))
        metrics = service_effectiveness_metrics(cutoff=now)
        self.assertEqual(metrics["cohort_total"], 2)
        self.assertEqual(metrics["cohort_completed"], 1)
        self.assertEqual(metrics["resolution_rate"], 50.0)
        self.assertEqual(metrics["average_response"], timedelta(hours=4))
        self.assertEqual(metrics["average_turnaround"], timedelta(days=1))
        self.assertEqual(metrics["open_backlog"], 1)

    def test_empty_metrics_are_na_instead_of_dividing_by_zero(self):
        metrics = service_effectiveness_metrics(ServiceRequest.objects.none())
        self.assertEqual(metrics["resolution_rate_display"], "N/A")
        self.assertEqual(metrics["average_response_display"], "N/A")

    def test_only_admin_can_change_service_targets(self):
        self.client.force_login(self.staff)
        denied = self.client.get(reverse("service_requests:service_levels"))
        self.assertEqual(denied.status_code, 302)
        self.client.force_login(self.admin)
        allowed = self.client.get(reverse("service_requests:service_levels"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "proposed operational defaults")

    def test_effectiveness_report_uses_shared_metric_service(self):
        self.request()
        title, headers, rows = build_report("service_effectiveness", "all")
        self.assertEqual(title, "Service Effectiveness Report")
        self.assertEqual(headers, ["Indicator", "Result", "Definition"])
        self.assertTrue(any(row[0] == "Open backlog" and row[1] == 1 for row in rows))
        self.client.force_login(self.staff)
        preview = self.client.get(
            reverse("reports:home"),
            {"report_type": "service_effectiveness", "date_range": "all"},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "Service Effectiveness Report")

    def test_metrics_keep_bounded_queries_above_five_thousand_requests(self):
        now = timezone.now()
        ServiceRequest.objects.bulk_create(
            [
                ServiceRequest(
                    farmer=self.farmer,
                    service=self.service,
                    priority="LOW",
                    status="PENDING",
                    first_response_due_at=now + timedelta(days=5),
                    due_at=now + timedelta(days=7),
                )
                for _ in range(5001)
            ],
            batch_size=500,
        )
        with CaptureQueriesContext(connection) as queries:
            metrics = service_effectiveness_metrics()
        self.assertEqual(metrics["open_backlog"], 5001)
        self.assertLessEqual(len(queries), 10)

    def test_overdue_filter_returns_only_overdue_open_requests(self):
        overdue = self.request()
        self.request(priority="LOW")
        ServiceRequest.objects.filter(pk=overdue.pk).update(
            first_response_due_at=timezone.now() - timedelta(hours=1)
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("service_requests:list"), {"overdue": "yes"})
        self.assertContains(response, overdue.request_id)
        self.assertEqual(len(response.context["object_list"]), 1)

    def test_list_uses_barangay_as_coverage_and_omits_beneficiary_column(self):
        item = self.request(
            farmer=None,
            scope="BARANGAY",
            target_barangay="Bagong Pook",
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("service_requests:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brgy. Bagong Pook")
        self.assertNotContains(response, "<th>Beneficiary</th>", html=True)
        self.assertContains(response, item.request_id)

    def test_association_scope_uses_active_farmer_registry_associations(self):
        Farmer.objects.create(
            first_name="Member",
            last_name="One",
            barangay="Alupay",
            is_association_member=True,
            fca_membership="Hog Raisers Association",
        )
        Farmer.objects.create(
            first_name="Member",
            last_name="Two",
            barangay="Bagong Pook",
            is_association_member=True,
            fca_membership="Hog Raisers Association",
        )
        form = ServiceRequestForm(
            data={
                "scope": "ASSOCIATION",
                "target_association": "Hog Raisers Association",
                "service": self.service.pk,
                "priority": "MEDIUM",
                "status": "PENDING",
                "notes": "Feed assistance request",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        request = form.save()
        self.assertEqual(request.target_association, "Hog Raisers Association")
        self.assertIsNone(request.farmer)
        self.assertEqual(
            dict(form.fields["target_association"].choices)["Hog Raisers Association"],
            "Hog Raisers Association (2 active members)",
        )

    def test_walk_in_scope_records_unregistered_requester_name(self):
        form = ServiceRequestForm(
            data={
                "scope": "WALK_IN",
                "walk_in_name": "Juan Dela Cruz",
                "service": self.service.pk,
                "priority": "LOW",
                "status": "PENDING",
                "notes": "Seeds requested for a school research activity",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        service_request = form.save()
        self.assertEqual(service_request.beneficiary_label, "Juan Dela Cruz")
        self.assertEqual(service_request.beneficiary_reference, "Walk-In")
        self.assertIsNone(service_request.farmer)
