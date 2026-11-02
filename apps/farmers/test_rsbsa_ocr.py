import json
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Farmer
from .rsbsa_scan import ocr_engine_selected, rsbsa_scan_available

SAMPLE = {"PROVIDER": "sample", "DAILY_LIMIT": 40}
OPENROUTER = {"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "MODELS": ["m1"], "DAILY_LIMIT": 40}


def photo(color=(210, 220, 210)):
    buffer = BytesIO()
    Image.new("RGB", (1200, 1600), color).save(buffer, format="PNG")
    return SimpleUploadedFile("rsbsa.png", buffer.getvalue(), content_type="image/png")


def reply(title="RSBSA Enrollment Form", **fields):
    values = {"form_title": title, "last_name": "Reyes", "first_name": "Ana", "sex": "FEMALE", "barangay": "Alupay", **fields}
    return json.dumps({"fields": {k: {"value": v, "confidence": 0.95} for k, v in values.items()}})


class RsbsaOcrEngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(username="rsbsastaff", password="Strong-password-731!", role="STAFF")

    def setUp(self):
        self.client.force_login(self.staff)

    def scan(self, upload=None):
        return self.client.post(reverse("farmers:scan_rsbsa"), {"rsbsa_scan": upload or photo()})

    @override_settings(RSBSA_SCAN_ENGINE="ocr", OCR=SAMPLE)
    def test_sample_engine_returns_profile_and_flags_unsure_fields(self):
        payloads = [self.scan(photo((i * 9, 200, 200))).json() for i in range(8)]
        self.assertTrue(all(p["fields"]["last_name"] for p in payloads))
        clean = next(p for p in payloads if p["fields"]["last_name"] == "Dela Cruz")
        self.assertEqual(clean["fields"]["birth_date"], "1980-05-17")
        self.assertEqual(clean["needs_review"], [])
        unsure = next(p for p in payloads if p["fields"]["last_name"] == "Bautista")
        self.assertIn("last_name", unsure["needs_review"])
        self.assertEqual(unsure["fields"]["birth_date"], "")  # 17/05/1975 is not a valid format
        self.assertIn("birth_date", unsure["needs_review"])
        self.assertEqual(unsure["fields"]["phone_number"], "09181234567")  # normalised, but under the threshold
        self.assertIn("phone_number", unsure["needs_review"])
        self.assertTrue(unsure["scan_token"])
        self.assertFalse(Farmer.objects.exists())  # reading never saves a farmer

    @override_settings(RSBSA_SCAN_ENGINE="auto", OCR=OPENROUTER)
    @mock.patch("apps.ocr.providers.requests.post")
    def test_auto_uses_the_configured_provider_and_normalises_values(self, post):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": reply(barangay="alupay", phone_number="+639171234567")}}]}
        post.return_value = response
        payload = self.scan().json()
        self.assertEqual((payload["fields"]["barangay"], payload["fields"]["phone_number"]), ("Alupay", "09171234567"))
        self.assertEqual(post.call_count, 1)
        self.assertIn("RSBSA Enrollment Form", post.call_args.kwargs["json"]["messages"][0]["content"][0]["text"])

    @override_settings(RSBSA_SCAN_ENGINE="auto", OCR=OPENROUTER)
    @mock.patch("apps.ocr.providers.requests.post")
    def test_other_documents_are_rejected(self, post):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": reply(title="Barangay Clearance")}}]}
        post.return_value = response
        result = self.scan()
        self.assertEqual(result.status_code, 422)
        self.assertIn("official RSBSA enrollment form", result.json()["error"])

    @override_settings(RSBSA_SCAN_ENGINE="auto", OCR=OPENROUTER)
    @mock.patch("apps.ocr.providers.requests.post")
    def test_provider_failure_is_a_clear_unavailable_message(self, post):
        post.return_value = mock.Mock(status_code=500)
        result = self.scan()
        self.assertEqual(result.status_code, 503)
        self.assertIn("temporarily unavailable", result.json()["error"])

    @override_settings(RSBSA_SCAN_ENGINE="ocr", OCR=SAMPLE)
    def test_pdf_is_not_supported_by_the_ocr_reader(self):
        pdf = SimpleUploadedFile("form.pdf", b"%PDF-1.4 content\n%%EOF", content_type="application/pdf")
        result = self.scan(pdf)
        self.assertEqual(result.status_code, 400)
        self.assertIn("must be a JPG, JPEG, PNG, WEBP", result.json()["error"])

    @override_settings(RSBSA_SCAN_ENGINE="ocr", OCR=SAMPLE)
    def test_several_pages_are_read_together(self):
        result = self.client.post(reverse("farmers:scan_rsbsa"), {"rsbsa_scan": [photo((1, 200, 200)), photo((2, 200, 200))]})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["fields"]["last_name"])

    @override_settings(RSBSA_SCAN_ENGINE="ocr", OCR=SAMPLE)
    def test_too_many_pages_are_refused(self):
        files = [photo((i * 10, 200, 200)) for i in range(4)]
        result = self.client.post(reverse("farmers:scan_rsbsa"), {"rsbsa_scan": files})
        self.assertEqual(result.status_code, 400)
        self.assertIn("at most 3 photos", result.json()["error"])

    @override_settings(RSBSA_SCAN_ENGINE="auto", OCR={**OPENROUTER, "DAILY_LIMIT": 1})
    @mock.patch("apps.ocr.providers.requests.post")
    def test_the_daily_limit_gives_a_clear_message(self, post):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{"message": {"content": reply()}}]}
        post.return_value = response
        self.assertEqual(self.scan(photo((1, 1, 1))).status_code, 200)
        second = self.scan(photo((2, 2, 2)))
        self.assertEqual(second.status_code, 429)
        self.assertIn("daily limit of 1", second.json()["error"])
        self.assertEqual(post.call_count, 1)

    def test_engine_choice(self):
        with override_settings(RSBSA_SCAN_ENGINE="auto", OCR=SAMPLE, OPENAI_API_KEY=""):
            self.assertFalse(ocr_engine_selected())  # sample data is never used by accident
            self.assertFalse(rsbsa_scan_available())
        with override_settings(RSBSA_SCAN_ENGINE="auto", OCR=OPENROUTER, OPENAI_API_KEY=""):
            self.assertTrue(ocr_engine_selected() and rsbsa_scan_available())
        with override_settings(RSBSA_SCAN_ENGINE="auto", OCR={**OPENROUTER, "OPENROUTER_API_KEY": ""}, OPENAI_API_KEY="x"):
            self.assertFalse(ocr_engine_selected())  # falls back to the OpenAI reader
            self.assertTrue(rsbsa_scan_available())
        with override_settings(RSBSA_SCAN_ENGINE="openai", OCR=OPENROUTER):
            self.assertFalse(ocr_engine_selected())


class SharedScanPanelTests(TestCase):
    """One panel template serves the farmer, parcel and commodity pages."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(username="panelstaff", password="Strong-password-731!", role="STAFF")

    def setUp(self):
        self.client.force_login(self.staff)

    def test_all_three_pages_use_the_same_panel(self):
        for name, target in (("farmers:create", "FARMER"), ("farm_parcels:create", "PARCEL"), ("crops:create", "CROP")):
            page = self.client.get(reverse(name))
            self.assertContains(page, "data-scan-panel", msg_prefix=name)
            self.assertContains(page, f'data-scan-target="{target}"', msg_prefix=name)
            self.assertContains(page, "data-scan-panel", msg_prefix=name)
            self.assertContains(page, "Scan &amp; Auto-Fill", msg_prefix=name)
            self.assertContains(page, "data-scan-add", msg_prefix=name)
            self.assertContains(page, "up to 5 MB per photo", msg_prefix=name)
            self.assertTemplateUsed(page, "form_scan/_scan_panel.html")

    @override_settings(RSBSA_SCAN_ENGINE="ocr", OCR=SAMPLE)
    def test_farmer_panel_reads_in_place_through_the_scan_endpoint(self):
        page = self.client.get(reverse("farmers:create"))
        self.assertContains(page, f'data-scan-url="{reverse("farmers:scan_rsbsa")}"')
        self.assertContains(page, 'data-scan-form="rsbsaRegistration"')
        self.assertContains(page, "scan-panel.js")
        self.assertNotContains(page, reverse("form_scan:upload"))  # no separate review page for farmers

    @override_settings(RSBSA_SCAN_ENGINE="auto", OCR=SAMPLE, OPENAI_API_KEY="")
    def test_farmer_panel_is_disabled_until_a_reader_is_configured(self):
        page = self.client.get(reverse("farmers:create"))
        self.assertNotContains(page, "data-scan-url")
        self.assertContains(page, "The form reader is not set up yet")
        self.assertContains(page, "data-scan-run disabled")

    def test_parcel_and_commodity_panels_open_the_review_screen(self):
        for name, target in (("farm_parcels:create", "PARCEL"), ("crops:create", "CROP")):
            page = self.client.get(reverse(name))
            self.assertContains(page, f'action="{reverse("form_scan:upload")}"')
            self.assertContains(page, f'name="target" value="{target}"')
