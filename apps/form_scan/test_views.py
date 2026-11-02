import shutil
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.activity_logs.models import ActivityLog
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.models import Farmer

from .models import FieldCorrection, FormScan, FormScanAudit

GOOD = {
    "farmer_name": "Dela Cruz, Juan", "barangay": "Bulihan", "parcel_name": "Bukid", "latitude": "13.7967",
    "longitude": "121.2351", "area_hectares": "1.5", "commodity": "Rice", "ownership_type": "OWNED",
}


def photo(size=(900, 1200), fmt="PNG", color=(120, 160, 120)):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=fmt)
    return buffer.getvalue()


def upload(content=None, name="form.png", **kwargs):
    return SimpleUploadedFile(name, content if content is not None else photo(**kwargs), content_type="image/png")


class ScanTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user(username="scanstaff", password="Strong-password-731!", role="STAFF")
        cls.admin = User.objects.create_user(username="scanadmin", password="Strong-password-731!", role="ADMIN")
        cls.farmer = Farmer.objects.create(first_name="Juan", last_name="Dela Cruz", barangay="Bulihan")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(settings.PRIVATE_MEDIA_ROOT, ignore_errors=True)

    def make_scan(self, fields=None, ocr_fields=None, ocr=True):
        fields = {**GOOD, **(fields or {})}
        scan = FormScan(
            created_by=self.staff, image_sha256="0" * 64, ocr_available=ocr, ocr_provider="openrouter" if ocr else "",
            ocr_model="m1" if ocr else "", fields=fields,
            ocr_fields=(ocr_fields if ocr_fields is not None else {k: {"value": v, "confidence": 0.95} for k, v in GOOD.items()}) if ocr else {},
        )
        scan.image.save("x.img", ContentFile(photo()), save=False)
        scan.save()
        return scan

    def approve(self, scan, **changes):
        data = {**GOOD, **changes, "farmer": self.farmer.pk, "action": "approve"}
        return self.client.post(reverse("form_scan:review", args=[scan.pk]), data)


class AccessTests(ScanTestCase):
    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(reverse("form_scan:upload"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_administrator_cannot_use_the_scanner(self):
        self.client.force_login(self.admin)
        scan = self.make_scan()
        for url in (reverse("form_scan:upload"), reverse("form_scan:review", args=[scan.pk]), reverse("form_scan:image", args=[scan.pk])):
            self.assertEqual(self.client.get(url).status_code, 302, url)
        self.assertEqual(self.client.post(reverse("form_scan:upload"), {"photo": upload()}).status_code, 302)
        self.assertFalse(FormScan.objects.exclude(pk=scan.pk).exists())

    def test_staff_can_open_the_page(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("form_scan:upload"))
        self.assertContains(response, "Scan &amp; Auto-Fill")
        self.assertContains(response, "Sample data mode")


class UploadValidationTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def post(self, file):
        return self.client.post(reverse("form_scan:upload"), {"photo": file})

    def test_rejects_a_file_that_is_not_an_image(self):
        response = self.post(upload(b"%PDF-1.4 not an image", name="form.png"))
        self.assertContains(response, "not a readable JPG, PNG or WebP")
        self.assertFalse(FormScan.objects.exists())

    def test_rejects_a_disallowed_image_type(self):
        response = self.post(upload(photo(fmt="GIF"), name="form.png"))
        self.assertContains(response, "Only JPG, PNG or WebP")

    def test_rejects_oversized_files(self):
        with override_settings(OCR={**settings.OCR, "MAX_IMAGE_BYTES": 1000}):
            response = self.post(upload())
        self.assertContains(response, "or smaller")

    def test_rejects_tiny_images(self):
        self.assertContains(self.post(upload(size=(200, 200))), "too small")

    def test_accepts_a_real_photo_and_ignores_the_file_name(self):
        response = self.post(upload(name="../../evil.php.png"))
        scan = FormScan.objects.get()
        self.assertRedirects(response, reverse("form_scan:review", args=[scan.pk]))
        self.assertNotIn("evil", scan.image.name)
        self.assertEqual(scan.created_by, self.staff)


class PrivateStorageTests(ScanTestCase):
    def test_image_is_stored_privately_and_served_only_to_staff(self):
        self.client.force_login(self.staff)
        self.client.post(reverse("form_scan:upload"), {"photo": upload()})
        scan = FormScan.objects.get()
        self.assertTrue(str(scan.image.path).startswith(str(settings.PRIVATE_MEDIA_ROOT)))
        self.assertFalse(str(scan.image.path).startswith(str(settings.MEDIA_ROOT)))
        response = self.client.get(reverse("form_scan:image", args=[scan.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        with self.assertRaises(ValueError):
            scan.image.url  # no public URL exists
        self.client.logout()
        self.assertEqual(self.client.get(reverse("form_scan:image", args=[scan.pk])).status_code, 302)


class OcrFlowTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_sample_ocr_prefills_fields_and_logs_the_model(self):
        self.client.post(reverse("form_scan:upload"), {"photo": upload()})
        scan = FormScan.objects.get()
        self.assertTrue(scan.ocr_available)
        self.assertEqual((scan.ocr_provider, scan.ocr_model), ("sample", "sample"))
        self.assertTrue(scan.fields["farmer_name"])
        self.assertIn(scan.traffic_light, {"GREEN", "YELLOW", "RED"})
        self.assertEqual(list(scan.audit.values_list("action", flat=True)), ["UPLOADED", "OCR_DONE"])

    @override_settings(OCR={"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "", "MODELS": []})
    def test_unavailable_ocr_falls_back_to_manual_entry(self):
        response = self.client.post(reverse("form_scan:upload"), {"photo": upload()}, follow=True)
        scan = FormScan.objects.get()
        self.assertFalse(scan.ocr_available)
        self.assertContains(response, "Manual entry")
        self.assertContains(response, "form reader is not available")
        self.assertIn("OCR_UNAVAILABLE", scan.audit.values_list("action", flat=True))

    @override_settings(OCR={"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "", "MODELS": []})
    def test_manual_entry_can_still_be_approved(self):
        self.client.post(reverse("form_scan:upload"), {"photo": upload()})
        scan = FormScan.objects.get()
        self.approve(scan)
        scan.refresh_from_db()
        self.assertEqual(scan.status, "APPROVED")
        self.assertEqual(scan.corrections.count(), 0)  # nothing from OCR to compare against


class ReviewScreenTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_low_confidence_fields_are_highlighted(self):
        ocr_fields = {k: {"value": v, "confidence": 0.95} for k, v in GOOD.items()}
        ocr_fields["area_hectares"]["confidence"] = 0.4
        scan = self.make_scan(ocr_fields=ocr_fields)
        response = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        self.assertContains(response, "sg-field sg-low", count=1)
        self.assertContains(response, "Low confidence")
        self.assertContains(response, "YELLOW")

    def test_red_scan_shows_suggestion_and_disables_approve(self):
        scan = self.make_scan({"latitude": "121.2351", "longitude": "13.7967"})
        response = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        self.assertContains(response, "Suggested: 13.796700, 121.235100")
        self.assertContains(response, "Use suggestion")
        self.assertContains(response, "disabled")
        self.assertContains(response, "Correct the red items")
        self.assertEqual(response.context["map_data"]["suggested"], (13.7967, 121.2351))

    def test_farmer_choices_match_the_name_on_the_form(self):
        Farmer.objects.create(first_name="Zed", last_name="Other", barangay="Alupay")
        scan = self.make_scan()
        response = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        names = [farmer.last_name for farmer in response.context["form"].fields["farmer"].queryset]
        self.assertEqual(names, ["Dela Cruz"])

    def test_recheck_stores_edits_and_logs_them(self):
        scan = self.make_scan({"latitude": "121.2351", "longitude": "13.7967"})
        response = self.client.post(
            reverse("form_scan:review", args=[scan.pk]),
            {**GOOD, "latitude": "13.796700", "longitude": "121.235100", "farmer": self.farmer.pk, "action": "check"},
        )
        self.assertRedirects(response, reverse("form_scan:review", args=[scan.pk]))
        scan.refresh_from_db()
        self.assertEqual(scan.traffic_light, "GREEN")
        self.assertEqual(scan.fields["latitude"], "13.796700")
        self.assertEqual(scan.audit.filter(action="CHECKED").count(), 1)
        # the original OCR reading is never overwritten
        self.assertEqual(scan.ocr_fields["latitude"]["value"], "13.7967")


class ApprovalTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_red_blocks_approval_on_the_server(self):
        scan = self.make_scan({"latitude": "14.5995", "longitude": "120.9842"})
        response = self.approve(scan, latitude="14.5995", longitude="120.9842")
        self.assertContains(response, "Red checks must be corrected")
        self.assertFalse(FarmParcel.objects.exists())
        scan.refresh_from_db()
        self.assertEqual((scan.status, scan.traffic_light), ("DRAFT", "RED"))

    def test_overlap_blocks_approval(self):
        FarmParcel.objects.create(farmer=self.farmer, barangay="Bulihan", area_hectares="1", ownership_type="OWNED", coordinates="13.7967000, 121.2351000")
        response = self.approve(self.make_scan())
        self.assertContains(response, "Red checks must be corrected")
        self.assertEqual(FarmParcel.objects.count(), 1)

    def test_green_approval_saves_parcel_crop_audit_and_activity(self):
        scan = self.make_scan()
        response = self.approve(scan)
        self.assertRedirects(response, reverse("form_scan:review", args=[scan.pk]))
        parcel = FarmParcel.objects.get()
        self.assertEqual((parcel.farmer, parcel.barangay, str(parcel.area_hectares)), (self.farmer, "Bulihan", "1.50"))
        self.assertEqual(parcel.coordinates, "13.7967000, 121.2351000")
        self.assertEqual(CropRecord.objects.get().crop_type, "Rice")
        scan.refresh_from_db()
        self.assertEqual((scan.status, scan.approved_by, scan.parcel), ("APPROVED", self.staff, parcel))
        approved = scan.audit.get(action="APPROVED")
        self.assertEqual(approved.detail["model"], "m1")
        self.assertEqual(approved.detail["status"], "GREEN")
        self.assertTrue(ActivityLog.objects.filter(title="Farm Parcel Created from Scan").exists())

    def test_corrections_store_original_and_final_values(self):
        scan = self.make_scan()
        self.approve(scan, area_hectares="2.5", commodity="Corn")
        corrections = {c.field_name: (c.ocr_value, c.final_value, c.ocr_model, c.corrected_by) for c in FieldCorrection.objects.all()}
        self.assertEqual(set(corrections), {"area_hectares", "commodity"})
        self.assertEqual(corrections["area_hectares"], ("1.5", "2.5", "m1", self.staff))
        self.assertEqual(scan.audit.get(action="APPROVED").detail["changed"], ["area_hectares", "commodity"])
        self.assertEqual(str(FarmParcel.objects.get().area_hectares), "2.50")

    def test_yellow_can_be_approved(self):
        ocr_fields = {k: {"value": v, "confidence": 0.3} for k, v in GOOD.items()}
        scan = self.make_scan(ocr_fields=ocr_fields)
        self.approve(scan)
        self.assertEqual(FarmParcel.objects.count(), 1)
        self.assertEqual(FormScan.objects.get().audit.get(action="APPROVED").detail["status"], "YELLOW")

    def test_dms_is_saved_as_decimal_and_flagged(self):
        scan = self.make_scan({"barangay": "San Isidro"})
        self.approve(scan, barangay="San Isidro", latitude="13°48'26.6\"N", longitude="121°18'54.7\"E")
        self.assertEqual(FarmParcel.objects.get().coordinates, "13.8073889, 121.3151944")
        self.assertTrue(FormScan.objects.get().audit.get(action="APPROVED").detail["converted_from_dms"])

    def test_missing_requirements_are_refused(self):
        scan = self.make_scan()
        self.assertContains(self.approve(scan, ownership_type=""), "Choose the ownership type")
        self.assertContains(self.approve(scan, area_hectares="0"), "Enter the farm area")
        self.assertContains(self.approve(scan, barangay="Nowhere"), "Choose a valid Rosario barangay")
        response = self.client.post(reverse("form_scan:review", args=[scan.pk]), {**GOOD, "action": "approve"})
        self.assertContains(response, "Choose the farmer")
        self.assertFalse(FarmParcel.objects.exists())

    def test_cannot_approve_twice_or_after_discard(self):
        scan = self.make_scan()
        self.approve(scan)
        self.approve(scan)
        self.assertEqual(FarmParcel.objects.count(), 1)

    def test_discard_keeps_the_record_and_creates_nothing(self):
        scan = self.make_scan()
        self.client.post(reverse("form_scan:review", args=[scan.pk]), {"action": "discard"})
        scan.refresh_from_db()
        self.assertEqual(scan.status, "DISCARDED")
        self.assertTrue(scan.audit.filter(action="DISCARDED").exists())
        self.assertFalse(FarmParcel.objects.exists())
        self.approve(scan)
        self.assertFalse(FarmParcel.objects.exists())
