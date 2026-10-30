from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest
from .models import (
    WeatherCoverageArea,
    WeatherMonitoringRule,
    WeatherObservation,
    WeatherRiskEvent,
)
from .services import WeatherAPIError, evaluate_rule, fetch_completed_day_rainfall


@override_settings(FMIS_WEATHER_LICENSE_REVIEWED=True, FMIS_REQUIRE_MFA=False)
class WeatherMonitoringTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="weatherstaff", password="FieldSecure!123", role="STAFF", is_active=True
        )
        self.area = WeatherCoverageArea.objects.create(
            code="north-grid", name="North Rosario grid", latitude="13.8400000",
            longitude="121.2100000", radius_km="5.00", is_active=True,
        )
        self.rule = WeatherMonitoringRule.objects.create(
            name="OAS test rainfall review", coverage_area=self.area,
            minimum_daily_rainfall_mm="10.00", consecutive_days=5,
            accumulated_rainfall_mm="150.00", suggested_priority="HIGH",
            cooldown_days=7, is_approved=True, is_active=True,
        )
        self.farmer = Farmer.objects.create(
            first_name="Fictional", last_name="Farmer", barangay="Bagong Pook"
        )
        self.parcel = FarmParcel.objects.create(
            farmer=self.farmer, barangay="Bagong Pook", area_hectares="1.00",
            ownership_type="OWNED", coordinates="13.8420000, 121.2120000",
        )
        CropRecord.objects.create(parcel=self.parcel, crop_type="Rice", variety="Demo")

    def _observations(self, values=(30, 30, 30, 30, 30)):
        end = timezone.localdate() - timedelta(days=1)
        start = end - timedelta(days=4)
        for offset, value in enumerate(values):
            WeatherObservation.objects.create(
                coverage_area=self.area, observed_date=start + timedelta(days=offset),
                precipitation_mm=value, source_url="https://open-meteo.com/en/docs",
                retrieved_at=timezone.now(), resolved_latitude=self.area.latitude,
                resolved_longitude=self.area.longitude, is_complete=True,
            )
        return end

    def test_api_validation_accepts_complete_daily_response(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "latitude": 13.84, "longitude": 121.21,
            "daily": {"time": ["2026-10-25"], "precipitation_sum": [12.5]},
        }
        session = Mock()
        session.get.return_value = response
        payload = fetch_completed_day_rainfall(
            self.area, timezone.localdate() - timedelta(days=2),
            timezone.localdate() - timedelta(days=2), session=session,
        )
        self.assertEqual(payload["rows"][0][1], Decimal("12.50"))
        self.assertEqual(session.get.call_args.kwargs["timeout"], (3.05, 12))

    def test_missing_rainfall_never_creates_event(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "latitude": 13.84, "longitude": 121.21,
            "daily": {"time": ["2026-10-25"], "precipitation_sum": [None]},
        }
        session = Mock()
        session.get.return_value = response
        with self.assertRaises(WeatherAPIError):
            fetch_completed_day_rainfall(
                self.area, timezone.localdate() - timedelta(days=2),
                timezone.localdate() - timedelta(days=2), session=session,
            )
        self.assertFalse(WeatherRiskEvent.objects.exists())

    def test_threshold_creates_one_idempotent_area_event_with_verified_parcel(self):
        end = self._observations()
        event, created = evaluate_rule(self.rule, period_end=end)
        self.assertTrue(created)
        self.assertEqual(event.parcel_links.count(), 1)
        duplicate, created_again = evaluate_rule(self.rule, period_end=end)
        self.assertFalse(created_again)
        self.assertEqual(duplicate.pk, event.pk)
        self.assertEqual(WeatherRiskEvent.objects.count(), 1)

    def test_incomplete_consecutive_period_does_not_trigger(self):
        end = self._observations(values=(30, 30, 30, 30))
        event, created = evaluate_rule(self.rule, period_end=end)
        self.assertIsNone(event)
        self.assertFalse(created)

    def test_demo_or_invalid_coordinates_are_excluded(self):
        self.parcel.remarks = "FMIS-DEMO-DATA: placeholder"
        self.parcel.save(update_fields=["remarks"])
        end = self._observations()
        event, _created = evaluate_rule(self.rule, period_end=end)
        self.assertEqual(event.parcel_links.count(), 0)
        self.assertEqual(event.excluded_parcel_count, 1)

    def test_staff_approval_creates_weather_request_and_dismissal_requires_reason(self):
        end = self._observations()
        event, _created = evaluate_rule(self.rule, period_end=end)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("weather_monitoring:event_review", args=[event.pk]),
            {"action": "approve", "assigned_to": self.staff.pk, "reason": "Inspect fields"},
        )
        self.assertRedirects(response, reverse("weather_monitoring:event_detail", args=[event.pk]))
        event.refresh_from_db()
        self.assertEqual(event.status, WeatherRiskEvent.STATUS_APPROVED)
        request = ServiceRequest.objects.get(weather_link__event=event)
        self.assertEqual(request.source, ServiceRequest.SOURCE_WEATHER)
        self.assertEqual(request.scope, "BARANGAY")
        self.assertIn("not proof of crop damage", request.notes)

    def test_manual_service_request_flow_remains_manual(self):
        from apps.service_catalog.models import ServiceCatalog
        service = ServiceCatalog.objects.create(
            code="TEST-WEATHER-MANUAL", name="Manual test", category="Other",
            description="Test", processing_time="Test",
        )
        request = ServiceRequest.objects.create(
            scope="INDIVIDUAL", farmer=self.farmer, service=service
        )
        self.assertEqual(request.source, ServiceRequest.SOURCE_MANUAL)

    @override_settings(FMIS_WEATHER_LICENSE_REVIEWED=False)
    def test_command_refuses_to_run_before_license_review(self):
        with self.assertRaisesMessage(Exception, "FMIS_WEATHER_LICENSE_REVIEWED"):
            call_command("monitor_weather")

    def test_admin_only_configuration_rejects_staff(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("weather_monitoring:settings"))
        self.assertRedirects(
            response, reverse("dashboard:home"), fetch_redirect_response=False
        )
