from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import get_commands
from django.test import TestCase


class WeatherTriggeredRequestRemovalTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="weather-removal-staff",
            password="StrongPass123!",
            role="STAFF",
            is_active=True,
        )
        self.client.force_login(self.staff)

    def test_weather_monitoring_endpoint_and_command_are_removed(self):
        self.assertEqual(self.client.get("/weather-monitoring/").status_code, 404)
        self.assertNotIn("monitor_weather", get_commands())

    def test_weather_monitoring_environment_settings_are_removed(self):
        self.assertFalse(hasattr(settings, "FMIS_WEATHER_LICENSE_REVIEWED"))
        self.assertFalse(hasattr(settings, "FMIS_WEATHER_SCHEDULER_CONFIGURED"))
        self.assertFalse(hasattr(settings, "FMIS_WEATHER_API_URL"))
        self.assertFalse(hasattr(settings, "FMIS_WEATHER_API_KEY"))

    def test_service_requests_restore_manual_interface(self):
        response = self.client.get("/requests/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Weather Review")
        self.assertNotContains(response, 'name="source"')
        self.assertContains(response, "New Request")

    def test_request_analytics_no_longer_show_weather_monitoring(self):
        response = self.client.get(
            "/reports/",
            {"analytics_tab": "requests", "analytics_date_range": "all"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Weather Risk Events")
        self.assertNotContains(response, "Awaiting Weather Review")
        self.assertContains(response, "SERVICE REQUEST STATUS")
