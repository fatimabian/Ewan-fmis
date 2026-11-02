from unittest import mock

from django.test import override_settings
from django.urls import reverse

from apps.activity_logs.models import ActivityLog

from .models import FormScan
from .test_views import ScanTestCase, upload

REAL = {"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "MODELS": ["m1"], "DAILY_LIMIT": 30}


class LegalPagesTests(ScanTestCase):
    def test_the_privacy_notice_explains_what_happens_to_scanned_forms(self):
        page = self.client.get(reverse("authentication:privacy"))
        self.assertContains(page, "Scanning paper forms (Scan &amp; Auto-Fill)")
        for sentence in ("What leaves FMIS", "deleted as soon as the record is saved", "never stored",
                         "at most 30 photos a day", "ask the Office not to have your form scanned"):
            self.assertContains(page, sentence)

    def test_the_terms_set_out_staff_duties_when_scanning(self):
        page = self.client.get(reverse("authentication:terms"))
        self.assertContains(page, "Scanning paper forms")
        for sentence in ("the farmer has been told", "Do not scan identity cards", "accept or reject each one", "Do not copy, download, or share the photos"):
            self.assertContains(page, sentence)

    def test_both_pages_are_public(self):
        for name in ("authentication:privacy", "authentication:terms"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class ConfirmationAtThePointOfUseTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_the_dialog_asks_for_confirmation_when_the_photo_leaves_the_system(self):
        with override_settings(OCR=REAL):
            for name in ("farm_parcels:create", "crops:create", "farmers:create"):
                page = self.client.get(reverse(name))
                self.assertContains(page, "data-scan-consent", msg_prefix=name)
                self.assertContains(page, "sent to an outside reading service", msg_prefix=name)
                self.assertContains(page, reverse("authentication:privacy"), msg_prefix=name)
                self.assertContains(page, reverse("authentication:terms"), msg_prefix=name)

    def test_sample_mode_sends_nothing_so_it_asks_for_nothing(self):
        for name in ("farm_parcels:create", "farmers:create"):
            self.assertNotContains(self.client.get(reverse(name)), "data-scan-consent")

    def test_the_server_refuses_a_scan_without_the_confirmation(self):
        with override_settings(OCR=REAL), mock.patch("apps.ocr.providers.requests.post") as post:
            response = self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
            self.assertEqual(response.status_code, 302)
            self.assertFalse(FormScan.objects.exists())
            post.assert_not_called()  # nothing was sent anywhere
            self.assertFalse(ActivityLog.objects.exists())
            self.assertIn("allowed to scan this form", " ".join(str(m) for m in response.wsgi_request._messages))

    def test_the_confirmation_is_recorded_in_the_audit_trail(self):
        with override_settings(OCR={**REAL, "MODELS": []}):
            self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL", "consent": "1"})
        self.assertTrue(FormScan.objects.get().audit.get(action="UPLOADED").detail["consent_confirmed"])

    def test_the_farmer_scan_needs_it_too(self):
        with override_settings(OCR=REAL, RSBSA_SCAN_ENGINE="auto"), mock.patch("apps.ocr.providers.requests.post") as post:
            refused = self.client.post(reverse("farmers:scan_rsbsa"), {"rsbsa_scan": upload()})
            self.assertEqual(refused.status_code, 400, refused.content[:300])
            self.assertIn("allowed to scan this form", refused.json()["error"])
            post.assert_not_called()

    def test_the_older_openai_reader_needs_it_as_well(self):
        with override_settings(OCR={"PROVIDER": "sample"}, RSBSA_SCAN_ENGINE="openai", OPENAI_API_KEY="k"), mock.patch("apps.farmers.rsbsa_scan.requests.post") as post:
            refused = self.client.post(reverse("farmers:scan_rsbsa"), {"rsbsa_scan": upload()})
            self.assertEqual(refused.status_code, 400)
            post.assert_not_called()
