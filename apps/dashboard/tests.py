from django.core.cache import cache
from django.test import TestCase, override_settings
from unittest.mock import patch

from apps.authentication.models import CustomUser
from apps.farmers.models import Farmer

from .services import (
    ADMIN_DASHBOARD_CACHE_KEY,
    STAFF_DASHBOARD_CACHE_KEY,
    _cached_dashboard,
)
from apps.reports.analytics import REPORT_METRICS_CACHE_KEY, report_metrics


class DashboardCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(DASHBOARD_CACHE_SECONDS=60)
    def test_dashboard_builder_is_reused_during_short_cache_window(self):
        calls = []

        def build():
            calls.append(True)
            return {"total": len(calls)}

        self.assertEqual(_cached_dashboard("test-dashboard", build), {"total": 1})
        self.assertEqual(_cached_dashboard("test-dashboard", build), {"total": 1})
        self.assertEqual(len(calls), 1)

    def test_account_change_invalidates_admin_dashboard(self):
        cache.set(ADMIN_DASHBOARD_CACHE_KEY, {"stale": True}, 60)
        CustomUser.objects.create_user(username="cache-admin", password="test-pass")
        self.assertIsNone(cache.get(ADMIN_DASHBOARD_CACHE_KEY))

    def test_operational_change_invalidates_staff_dashboard(self):
        cache.set(STAFF_DASHBOARD_CACHE_KEY, {"stale": True}, 60)
        cache.set(REPORT_METRICS_CACHE_KEY, {"stale": True}, 60)
        Farmer.objects.create(first_name="Cache", last_name="Farmer", barangay="Alupay")
        self.assertIsNone(cache.get(STAFF_DASHBOARD_CACHE_KEY))
        self.assertIsNone(cache.get(REPORT_METRICS_CACHE_KEY))

    @override_settings(DASHBOARD_CACHE_SECONDS=60)
    @patch("apps.reports.analytics._build_report_metrics")
    def test_unfiltered_report_metrics_are_reused(self, build_metrics):
        build_metrics.return_value = {"farmers": 4}

        self.assertEqual(report_metrics("all", {}), {"farmers": 4})
        self.assertEqual(report_metrics("all", {}), {"farmers": 4})

        self.assertEqual(build_metrics.call_count, 1)
