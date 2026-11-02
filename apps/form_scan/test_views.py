import shutil
from io import BytesIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
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
    "farmer_name": "Dela Cruz, Juan", "barangay": "Bulihan", "latitude": "13.7967",
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

    def make_scan(self, fields=None, ocr_fields=None, ocr=True, target="PARCEL"):
        fields = {**GOOD, **(fields or {})}
        scan = FormScan(
            created_by=self.staff, image_sha256="0" * 64, ocr_available=ocr, ocr_provider="openrouter" if ocr else "",
            ocr_model="m1" if ocr else "", fields=fields, target=target,
            ocr_fields=(ocr_fields if ocr_fields is not None else {k: {"value": v, "confidence": 0.95} for k, v in GOOD.items()}) if ocr else {},
        )
        scan.image.save("x.img", ContentFile(photo()), save=False)
        scan.save()
        return scan

    def confirm(self, scan, **changes):
        data = {**GOOD, **changes, "farmer": self.farmer.pk, "action": "confirm"}
        return self.client.post(reverse("form_scan:review", args=[scan.pk]), data)

    def parcel_form(self, scan, **changes):
        """What the Add Farm Parcel form posts after it was opened from the scan."""
        data = {"farmer": self.farmer.pk, "barangay": "Bulihan", "municipality": "Rosario", "province": "Batangas",
                "area_hectares": "1.50", "ownership_type": "OWNED", "land_type": "UPLAND", "farm_type": "Irrigated",
                "is_rsbsa_recorded": "False", "coordinates": "13.7967000, 121.2351000",
                "is_active": "on", "scan": scan.pk, **changes}
        return self.client.post(reverse("farm_parcels:create"), data)


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

    def test_the_upload_address_sends_staff_back_to_the_form(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("form_scan:upload"))
        self.assertRedirects(response, reverse("farm_parcels:create"))

    def test_the_dialog_states_the_limits(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("farm_parcels:create"))
        self.assertContains(page, "File types:</strong> JPG, JPEG, PNG, WEBP")
        self.assertContains(page, "up to 5 MB per photo")
        self.assertContains(page, "up to 3 photos per scan")
        self.assertContains(page, "30 photos a day for the whole office")
        self.assertContains(page, "data-scan-add")
        self.assertContains(page, 'data-scan-count')
        self.assertContains(page, "Sample data mode")


class UploadValidationTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def post(self, *files, target="PARCEL"):
        return self.client.post(reverse("form_scan:upload"), {"photo": list(files), "target": target})

    def refused(self, response):
        """The upload is refused: back to the form with a message and no scan."""
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FormScan.objects.exists())
        return " ".join(str(m) for m in get_messages(response.wsgi_request))

    def test_rejects_a_file_that_is_not_an_image(self):
        self.assertIn("not a readable", self.refused(self.post(upload(b"%PDF-1.4 not an image", name="form.png"))))

    def test_rejects_a_disallowed_file_type(self):
        self.assertIn("must be a JPG, JPEG, PNG, WEBP", self.refused(self.post(upload(photo(), name="form.gif"))))
        self.assertIn("must be a JPG, JPEG, PNG, WEBP", self.refused(self.post(upload(b"%PDF-1.4", name="form.pdf"))))

    def test_rejects_oversized_files_with_the_limit_in_the_message(self):
        with override_settings(OCR={**settings.OCR, "MAX_IMAGE_BYTES": 1024 * 1024}):
            message = self.refused(self.post(upload(b"x" * (2 * 1024 * 1024), name="big.png")))
        self.assertIn("2.0 MB", message)
        self.assertIn("1 MB or smaller", message)

    def test_rejects_tiny_images(self):
        self.assertIn("too small", self.refused(self.post(upload(size=(200, 200)))))

    def test_rejects_too_many_pages(self):
        files = [upload(color=(i * 20, 0, 0)) for i in range(4)]
        self.assertIn("at most 3 photos", self.refused(self.post(*files)))

    def test_rejects_a_missing_photo(self):
        self.assertIn("Choose at least one photo", self.refused(self.post()))

    def test_accepts_a_real_photo_and_ignores_the_file_name(self):
        response = self.post(upload(name="../../evil.php.png"))
        scan = FormScan.objects.get()
        self.assertRedirects(response, reverse("form_scan:review", args=[scan.pk]))
        self.assertNotIn("evil", scan.image.name)
        self.assertEqual(scan.created_by, self.staff)


class MultiPageTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_three_pages_are_stored_privately_and_shown_on_the_review_screen(self):
        files = [upload(color=(10 * i, 50, 50)) for i in range(1, 4)]
        self.client.post(reverse("form_scan:upload"), {"photo": files, "target": "PARCEL"})
        scan = FormScan.objects.get()
        self.assertEqual(scan.page_numbers, [1, 2, 3])
        for page in (1, 2, 3):
            url = reverse("form_scan:page", args=[scan.pk, page])
            self.assertEqual(self.client.get(url).status_code, 200, page)
        self.assertEqual(self.client.get(reverse("form_scan:page", args=[scan.pk, 4])).status_code, 404)
        review = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        self.assertContains(review, "Page 3 of 3")
        for page in scan.extra_pages.all():
            self.assertTrue(str(page.image.path).startswith(str(settings.PRIVATE_MEDIA_ROOT)))
        self.assertEqual(scan.audit.get(action="UPLOADED").detail["pages"], 3)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("form_scan:page", args=[scan.pk, 2])).status_code, 302)

    def test_a_single_photo_shows_no_page_labels(self):
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
        review = self.client.get(reverse("form_scan:review", args=[FormScan.objects.get().pk]))
        self.assertNotContains(review, "Page 1 of 1")

    def test_the_daily_limit_keeps_the_photos_but_uses_manual_entry(self):
        providers = {"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "MODELS": ["m1"], "DAILY_LIMIT": 2}
        with override_settings(OCR=providers):
            from apps.ocr.models import OcrDailyUsage
            from django.utils import timezone

            OcrDailyUsage.objects.create(date=timezone.localdate(), count=2)
            response = self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"}, follow=True)
        scan = FormScan.objects.get()
        self.assertFalse(scan.ocr_available)
        self.assertIn("daily limit of 2", scan.ocr_message)
        self.assertContains(response, "Manual entry")

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
        self.assertContains(response, "open for manual entry")
        self.assertIn("OCR_UNAVAILABLE", scan.audit.values_list("action", flat=True))

    @override_settings(OCR={"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "", "MODELS": []})
    def test_manual_entry_can_still_be_approved(self):
        self.client.post(reverse("form_scan:upload"), {"photo": upload()})
        scan = FormScan.objects.get()
        self.confirm(scan)
        scan.refresh_from_db()
        self.assertEqual(scan.status, "CONFIRMED")
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
        labels = [label for _value, label in response.context["form"].fields["farmer"].choices if _value]
        self.assertEqual(labels, ["Juan Dela Cruz · Bulihan"])

    def test_best_name_matches_come_first(self):
        Farmer.objects.create(first_name="Mario", last_name="Cruz", barangay="Alupay")
        scan = self.make_scan()
        response = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        labels = [label for _value, label in response.context["form"].fields["farmer"].choices if _value]
        self.assertEqual(labels[0], "Juan Dela Cruz · Bulihan")

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


class ConfirmTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_confirm_stores_prefill_and_sends_staff_to_the_parcel_form(self):
        scan = self.make_scan()
        response = self.confirm(scan)
        self.assertRedirects(response, f"{reverse('farm_parcels:create')}?scan={scan.pk}&farmer={self.farmer.pk}")
        scan.refresh_from_db()
        self.assertEqual(scan.status, "CONFIRMED")
        self.assertEqual(scan.approved_by, self.staff)
        self.assertEqual(scan.prefill, {"farmer": self.farmer.pk, "barangay": "Bulihan", "area_hectares": "1.50",
                                         "ownership_type": "OWNED", "coordinates": "13.7967000, 121.2351000"})
        self.assertFalse(FarmParcel.objects.exists())  # nothing is saved until the form is saved

    def test_red_cannot_be_confirmed(self):
        scan = self.make_scan({"latitude": "14.5995", "longitude": "120.9842"})
        response = self.confirm(scan, latitude="14.5995", longitude="120.9842")
        self.assertContains(response, "Red checks must be corrected")
        scan.refresh_from_db()
        self.assertEqual((scan.status, scan.traffic_light), ("DRAFT", "RED"))

    def test_overlap_cannot_be_confirmed(self):
        FarmParcel.objects.create(farmer=self.farmer, barangay="Bulihan", area_hectares="1", ownership_type="OWNED", coordinates="13.7967000, 121.2351000")
        self.assertContains(self.confirm(self.make_scan()), "Red checks must be corrected")

    def test_missing_requirements_are_refused(self):
        scan = self.make_scan()
        self.assertContains(self.confirm(scan, area_hectares="0"), "Enter the farm area")
        self.assertContains(self.confirm(scan, barangay="Nowhere"), "Choose a valid Rosario barangay")
        scan.refresh_from_db()
        self.assertEqual(scan.status, "DRAFT")

    def test_dms_is_confirmed_as_decimal_and_flagged(self):
        scan = self.make_scan({"barangay": "San Isidro"})
        self.confirm(scan, barangay="San Isidro", latitude="13°48'26.6\"N", longitude="121°18'54.7\"E")
        scan.refresh_from_db()
        self.assertEqual(scan.prefill["coordinates"], "13.8073889, 121.3151944")
        self.assertTrue(scan.audit.get(action="CONFIRMED").detail["converted_from_dms"])

    def test_discard_keeps_the_record(self):
        scan = self.make_scan()
        self.client.post(reverse("form_scan:review", args=[scan.pk]), {"action": "discard"})
        scan.refresh_from_db()
        self.assertEqual(scan.status, "DISCARDED")
        self.assertTrue(scan.audit.filter(action="DISCARDED").exists())

    def test_commodity_target_needs_a_listed_commodity(self):
        scan = self.make_scan(target="CROP")
        self.assertContains(self.confirm(scan, commodity="Moon dust"), "Choose a commodity from the list")
        response = self.confirm(scan, commodity="rice", area_hectares="1.5")
        self.assertRedirects(response, f"{reverse('crops:create')}?scan={scan.pk}&farmer={self.farmer.pk}")
        scan.refresh_from_db()
        self.assertEqual(scan.prefill, {"crop_type": "Rice", "area_hectares": "1.50"})


class FormIntegrationTests(ScanTestCase):
    """The scan lives inside the existing forms: entry panel, prefill, save, audit."""

    def setUp(self):
        self.client.force_login(self.staff)

    def test_forms_offer_the_scan_and_navigation_does_not(self):
        parcel = self.client.get(reverse("farm_parcels:create"))
        self.assertContains(parcel, "data-scan-panel")
        self.assertContains(parcel, 'name="target" value="PARCEL"')
        crop = self.client.get(reverse("crops:create"))
        self.assertContains(crop, 'name="target" value="CROP"')
        self.assertNotContains(parcel, "Scan &amp; Auto-Fill</span>")  # no sidebar item

    def test_entry_panel_is_not_shown_when_editing(self):
        parcel = FarmParcel.objects.create(farmer=self.farmer, barangay="Bulihan", area_hectares="1", ownership_type="OWNED")
        self.assertNotContains(self.client.get(reverse("farm_parcels:edit", args=[parcel.pk])), "data-scan-panel")

    def test_upload_from_the_form_goes_to_review_with_the_target_and_farmer(self):
        response = self.client.post(reverse("form_scan:upload"), {"photo": upload(), "target": "CROP", "farmer": self.farmer.pk})
        scan = FormScan.objects.get()
        self.assertEqual(scan.target, "CROP")
        self.assertRedirects(response, f"{reverse('form_scan:review', args=[scan.pk])}?farmer={self.farmer.pk}")

    def test_confirmed_values_prefill_the_parcel_form(self):
        scan = self.make_scan()
        self.confirm(scan)
        page = self.client.get(reverse("farm_parcels:create"), {"scan": scan.pk, "farmer": self.farmer.pk})
        self.assertContains(page, f"Filled in from scan #{scan.pk}")
        self.assertContains(page, f'name="scan" value="{scan.pk}"')
        initial = page.context["form"].initial
        self.assertEqual((initial["barangay"], initial["area_hectares"], initial["coordinates"]), ("Bulihan", "1.50", "13.7967000, 121.2351000"))
        self.assertNotContains(page, "data-scan-panel")

    def test_unconfirmed_or_wrong_target_scans_do_not_prefill(self):
        draft, crop = self.make_scan(), self.make_scan(target="CROP")
        self.confirm(crop, commodity="Rice")
        for scan in (draft, crop):
            page = self.client.get(reverse("farm_parcels:create"), {"scan": scan.pk})
            self.assertNotContains(page, "Filled in from scan")

    def test_saving_the_form_finalizes_the_scan_with_audit_and_corrections(self):
        scan = self.make_scan()
        self.confirm(scan)
        response = self.parcel_form(scan, area_hectares="2.50")  # staff change the area in the form
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        parcel = FarmParcel.objects.get()
        scan.refresh_from_db()
        self.assertEqual((scan.status, scan.parcel, scan.farmer, scan.approved_by), ("APPROVED", parcel, self.farmer, self.staff))
        saved = scan.audit.get(action="SAVED")
        self.assertEqual((saved.detail["model"], saved.detail["changed"]), ("m1", ["area_hectares"]))
        correction = FieldCorrection.objects.get()
        self.assertEqual((correction.field_name, correction.ocr_value, correction.final_value, correction.ocr_model, correction.corrected_by),
                         ("area_hectares", "1.5", "2.50", "m1", self.staff))
        self.assertTrue(ActivityLog.objects.filter(title="Scanned Form Saved", module="Scan & Auto-Fill").exists())

    def test_unchanged_values_make_no_corrections(self):
        scan = self.make_scan()
        self.confirm(scan)
        self.parcel_form(scan)
        self.assertFalse(FieldCorrection.objects.exists())

    def test_a_scan_is_saved_only_once(self):
        scan = self.make_scan()
        self.confirm(scan)
        self.parcel_form(scan)
        self.parcel_form(scan, coordinates="13.8100000, 121.2400000")
        scan.refresh_from_db()
        self.assertEqual(scan.audit.filter(action="SAVED").count(), 1)

    def test_a_red_edit_in_the_form_is_blocked(self):
        scan = self.make_scan()
        self.confirm(scan)
        response = self.parcel_form(scan, coordinates="14.5995000, 120.9842000")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The scan check is red")
        self.assertFalse(FarmParcel.objects.exists())
        scan.refresh_from_db()
        self.assertEqual(scan.status, "CONFIRMED")

    def test_form_without_a_scan_saves_as_before(self):
        response = self.client.post(reverse("farm_parcels:create"), {
            "farmer": self.farmer.pk, "barangay": "Bulihan", "municipality": "Rosario", "province": "Batangas",
            "area_hectares": "1.00", "ownership_type": "OWNED", "land_type": "UPLAND", "farm_type": "Irrigated",
            "is_rsbsa_recorded": "False", "is_active": "on"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(FarmParcel.objects.count(), 1)
        self.assertFalse(FormScan.objects.exists())

    def test_commodity_form_prefill_and_save(self):
        parcel = FarmParcel.objects.create(farmer=self.farmer, barangay="Bulihan", area_hectares="2", ownership_type="OWNED")
        scan = self.make_scan(target="CROP")
        self.confirm(scan, commodity="Rice", area_hectares="1.5")
        page = self.client.get(reverse("crops:create"), {"scan": scan.pk, "farmer": self.farmer.pk})
        self.assertEqual((page.context["form"].initial["crop_type"], page.context["form"].initial["area_hectares"]), ("Rice", "1.50"))
        response = self.client.post(reverse("crops:create"), {"parcel": parcel.pk, "crop_type": "Rice", "area_hectares": "1.50", "is_organic": "False", "is_intercrop": "False", "scan": scan.pk})
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        scan.refresh_from_db()
        self.assertEqual((scan.status, scan.crop.crop_type), ("APPROVED", "Rice"))
