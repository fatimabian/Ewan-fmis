import json
import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.activity_logs.models import ActivityLog
from apps.farm_parcels.models import FarmParcel
from apps.notifications.models import Notification

from .models import FormScan, FormScanPage
from .services import expire_stale_scans
from .test_views import GOOD, ScanTestCase, photo, upload


def paths(scan):
    """Every photo file path a scan still has on disk."""
    found = [scan.image.path] if scan.image else []
    return found + [page.image.path for page in scan.extra_pages.all()]


class PhotoDeletionTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def two_page_scan(self, **kwargs):
        scan = self.make_scan(**kwargs)
        from django.core.files.base import ContentFile

        page = FormScanPage(scan=scan, position=2, image_sha256="1" * 64)
        page.image.save("p2.img", ContentFile(photo(color=(9, 9, 9))), save=True)
        return scan

    def test_photos_are_deleted_when_the_record_is_saved(self):
        scan = self.two_page_scan()
        self.confirm(scan)
        files = paths(scan)
        self.assertEqual(len(files), 2)
        self.assertTrue(all(os.path.exists(path) for path in files))  # kept while staff compare with the form
        self.parcel_form(scan)
        scan.refresh_from_db()
        self.assertEqual(scan.status, "APPROVED")
        self.assertFalse(any(os.path.exists(path) for path in files))
        self.assertIsNotNone(scan.files_deleted_at)
        self.assertFalse(scan.image)
        self.assertEqual(scan.extra_pages.count(), 0)
        self.assertEqual(scan.page_numbers, [])
        self.assertEqual(scan.audit.get(action="FILES_DELETED").detail["photos"], 2)
        # the text trail and corrections survive
        self.assertTrue(scan.audit.filter(action="SAVED").exists())
        self.assertEqual(self.client.get(reverse("form_scan:image", args=[scan.pk])).status_code, 404)
        review = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        self.assertContains(review, "photos were deleted")

    def test_photos_are_deleted_when_the_review_is_discarded(self):
        scan = self.two_page_scan()
        files = paths(scan)
        response = self.client.post(reverse("form_scan:review", args=[scan.pk]), {"action": "discard"})
        self.assertRedirects(response, reverse("farm_parcels:create"))
        scan.refresh_from_db()
        self.assertEqual(scan.status, "DISCARDED")
        self.assertFalse(any(os.path.exists(path) for path in files))
        self.assertTrue(ActivityLog.objects.filter(title="Scan Discarded", module="Scan & Auto-Fill").exists())

    def test_discarding_from_the_prefilled_form_starts_it_blank(self):
        scan = self.make_scan()
        self.confirm(scan)
        page = self.client.get(reverse("farm_parcels:create"), {"scan": scan.pk})
        self.assertContains(page, reverse("form_scan:discard", args=[scan.pk]))
        self.assertContains(page, "photos are deleted as soon as you save")
        files = paths(scan)
        response = self.client.post(reverse("form_scan:discard", args=[scan.pk]))
        self.assertRedirects(response, reverse("farm_parcels:create"))
        scan.refresh_from_db()
        self.assertEqual(scan.status, "DISCARDED")
        self.assertFalse(any(os.path.exists(path) for path in files))
        # a discarded scan can no longer fill a form or be saved
        blank = self.client.get(reverse("farm_parcels:create"), {"scan": scan.pk})
        self.assertNotContains(blank, "Filled in from scan")
        self.parcel_form(scan)
        scan.refresh_from_db()
        self.assertEqual(scan.status, "DISCARDED")

    def test_a_newer_scan_replaces_the_unfinished_one(self):
        old = self.make_scan()
        self.confirm(old)
        files = paths(old)
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
        old.refresh_from_db()
        self.assertEqual(old.status, "DISCARDED")
        self.assertEqual(old.audit.get(action="DISCARDED").detail["reason"], "Replaced by a newer scan")
        self.assertFalse(any(os.path.exists(path) for path in files))
        self.assertEqual(FormScan.objects.exclude(pk=old.pk).get().status, "DRAFT")

    def test_other_targets_and_other_staff_are_left_alone(self):
        other_target = self.make_scan(target="CROP")
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
        other_target.refresh_from_db()
        self.assertEqual(other_target.status, "DRAFT")


class ExpiryTests(ScanTestCase):
    def age(self, scan, hours):
        FormScan.objects.filter(pk=scan.pk).update(updated_at=timezone.now() - timedelta(hours=hours))

    def test_unfinished_scans_are_cleared_after_the_retention_time(self):
        old, fresh, confirmed = self.make_scan(), self.make_scan(), self.make_scan()
        self.client.force_login(self.staff)
        self.confirm(confirmed)
        self.age(old, 30)
        self.age(confirmed, 25)
        self.age(fresh, 2)
        files = paths(old) + paths(confirmed)
        self.assertEqual(expire_stale_scans(), 2)
        for scan, status in ((old, "EXPIRED"), (confirmed, "EXPIRED"), (fresh, "DRAFT")):
            scan.refresh_from_db()
            self.assertEqual(scan.status, status)
        self.assertFalse(any(os.path.exists(path) for path in files))
        self.assertTrue(os.path.exists(paths(fresh)[0]))
        self.assertEqual(old.audit.filter(action__in=["EXPIRED", "FILES_DELETED"]).count(), 2)
        event = ActivityLog.objects.get(title="Unfinished Scans Cleared")
        self.assertIsNone(event.actor)
        self.assertIn("2 scans", event.description)

    def test_the_retention_time_is_configurable(self):
        scan = self.make_scan()
        self.age(scan, 5)
        with override_settings(OCR={**__import__("django.conf").conf.settings.OCR, "RETENTION_HOURS": 4}):
            self.assertEqual(expire_stale_scans(), 1)

    def test_an_expired_scan_cannot_fill_or_save_a_form(self):
        scan = self.make_scan()
        self.client.force_login(self.staff)
        self.confirm(scan)
        self.age(scan, 30)
        expire_stale_scans()
        page = self.client.get(reverse("farm_parcels:create"), {"scan": scan.pk})
        self.assertNotContains(page, "Filled in from scan")
        self.parcel_form(scan)
        self.assertEqual(FormScan.objects.get(pk=scan.pk).status, "EXPIRED")

    def test_the_command_clears_and_also_removes_stray_photos(self):
        stale, finished = self.make_scan(), self.make_scan()
        FormScan.objects.filter(pk=finished.pk).update(status="APPROVED")  # finished but photos left behind
        self.age(stale, 48)
        call_command("purge_form_scans")
        stale.refresh_from_db()
        finished.refresh_from_db()
        self.assertEqual(stale.status, "EXPIRED")
        self.assertFalse(finished.image)
        self.assertIsNotNone(finished.files_deleted_at)

    def test_uploading_also_clears_old_scans(self):
        old = self.make_scan()
        self.age(old, 40)
        self.client.force_login(self.staff)
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "CROP"})
        old.refresh_from_db()
        self.assertEqual(old.status, "EXPIRED")


class AcceptRejectTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    def post(self, scan, accept, action="confirm", **changes):
        data = {**GOOD, **changes, "farmer": self.farmer.pk, "action": action, "accept_sent": "1", "accept": accept}
        return self.client.post(reverse("form_scan:review", args=[scan.pk]), data)

    def test_only_accepted_groups_reach_the_form(self):
        scan = self.make_scan()
        self.post(scan, ["barangay", "area_hectares"])
        scan.refresh_from_db()
        self.assertEqual(scan.status, "CONFIRMED")
        self.assertEqual(scan.rejected_groups, ["location", "ownership_type"])
        self.assertEqual(scan.prefill["barangay"], "Bulihan")
        self.assertEqual((scan.prefill["coordinates"], scan.prefill["ownership_type"]), ("", ""))
        confirmed = scan.audit.get(action="CONFIRMED").detail
        self.assertEqual(confirmed["accepted"], ["barangay", "area_hectares"])
        self.assertEqual(confirmed["rejected"], ["location", "ownership_type"])
        page = self.client.get(reverse("farm_parcels:create"), {"scan": scan.pk})
        initial = page.context["form"].initial
        self.assertEqual(initial["barangay"], "Bulihan")
        self.assertNotIn("coordinates", initial)
        self.assertNotIn("ownership_type", initial)

    def test_a_rejected_wrong_location_no_longer_blocks_confirming(self):
        scan = self.make_scan({"latitude": "14.5995", "longitude": "120.9842"})
        refused = self.post(scan, ["barangay", "location", "area_hectares", "ownership_type"], latitude="14.5995", longitude="120.9842")
        self.assertContains(refused, "Red checks must be corrected")
        accepted = self.post(scan, ["barangay", "area_hectares", "ownership_type"], latitude="14.5995", longitude="120.9842")
        self.assertEqual(accepted.status_code, 302)
        scan.refresh_from_db()
        self.assertEqual((scan.status, scan.prefill["coordinates"]), ("CONFIRMED", ""))

    def test_nothing_ticked_confirms_an_empty_form(self):
        scan = self.make_scan()
        self.post(scan, [])
        scan.refresh_from_db()
        self.assertEqual(set(scan.rejected_groups), {"barangay", "location", "area_hectares", "ownership_type"})
        self.assertEqual({v for k, v in scan.prefill.items() if k != "farmer"}, {""})

    def test_the_choice_is_remembered_between_checks_and_shown_on_screen(self):
        scan = self.make_scan()
        self.post(scan, ["barangay", "area_hectares", "ownership_type"], action="check")
        scan.refresh_from_db()
        self.assertEqual(scan.rejected_groups, ["location"])
        review = self.client.get(reverse("form_scan:review", args=[scan.pk]))
        self.assertContains(review, 'name="accept" value="barangay" checked')
        self.assertNotContains(review, 'name="accept" value="location" checked')
        self.assertContains(review, "Follows the location choice above")
        self.assertContains(review, "Not used in this form")  # commodity belongs to the commodity form

    def test_a_ticked_but_invalid_value_is_refused_with_a_hint(self):
        scan = self.make_scan()
        self.assertContains(self.post(scan, ["barangay", "area_hectares"], barangay="Nowhere"), "or untick it")

    def test_commodity_target_has_its_own_groups(self):
        scan = self.make_scan(target="CROP")
        self.post(scan, ["commodity"], commodity="Rice")
        scan.refresh_from_db()
        self.assertEqual(scan.rejected_groups, ["area_hectares"])
        self.assertEqual(scan.prefill, {"crop_type": "Rice", "area_hectares": ""})


class AuditAndNotificationTests(ScanTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.other_staff = User.objects.create_user(username="otherstaff", password="Strong-password-731!", role="STAFF")
        cls.office_admin = User.objects.create_user(username="officeadmin", password="Strong-password-731!", role="ADMIN")

    def setUp(self):
        self.client.force_login(self.staff)

    def titles(self):
        return list(ActivityLog.objects.order_by("pk").values_list("title", flat=True))

    def test_each_step_is_logged_once_with_the_right_meaning(self):
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
        scan = FormScan.objects.get()
        self.assertEqual(self.titles(), ["Form Scanned"])
        review = reverse("form_scan:review", args=[scan.pk])
        self.client.post(review, {**GOOD, "farmer": self.farmer.pk, "action": "check", "accept_sent": "1", "accept": ["barangay"]})
        self.assertEqual(self.titles(), ["Form Scanned"])  # re-checking is not a record change
        self.client.post(review, {**GOOD, "latitude": "13.7967", "longitude": "121.2351", "farmer": self.farmer.pk,
                                  "action": "confirm", "accept_sent": "1", "accept": ["barangay", "location", "area_hectares", "ownership_type"]})
        self.assertEqual(self.titles(), ["Form Scanned", "Scan Confirmed"])
        self.assertFalse(ActivityLog.objects.filter(title="System Record Updated").exists())
        event = ActivityLog.objects.get(title="Form Scanned")
        self.assertEqual((event.module, event.actor), ("Scan & Auto-Fill", self.staff))
        self.assertIn("Farm Parcel form", event.description)
        self.assertNotIn("Dela Cruz", event.description + event.target_label)  # no personal data in the log text

    def test_a_refused_upload_is_not_logged_as_a_change(self):
        self.client.post(reverse("form_scan:upload"), {"photo": [upload(b"junk", name="x.png")], "target": "PARCEL"})
        self.assertEqual(self.titles(), [])

    def test_saving_the_form_keeps_the_normal_record_audit_beside_the_scan_entry(self):
        scan = self.make_scan()
        self.confirm(scan)
        self.parcel_form(scan, area_hectares="2.00")
        titles = self.titles()
        self.assertIn("Scanned Form Saved", titles)
        self.assertTrue(any(title.startswith("Farm Parcel") for title in titles), titles)  # the standard entry
        self.assertTrue(FarmParcel.objects.exists())

    def test_scan_events_do_not_notify_staff(self):
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
        scan = FormScan.objects.get()
        self.confirm(scan)
        self.parcel_form(scan)
        self.assertFalse(Notification.objects.filter(source_activity__module="Scan & Auto-Fill").exists())

    def test_reaching_the_daily_limit_warns_administrators_once_a_day(self):
        providers = {"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "MODELS": ["m1"], "DAILY_LIMIT": 1}
        from apps.ocr.models import OcrDailyUsage

        OcrDailyUsage.objects.create(date=timezone.localdate(), count=1)
        with override_settings(OCR=providers):
            self.client.post(reverse("form_scan:upload"), {"photo": [upload(color=(1, 2, 3))], "target": "PARCEL", "consent": "1"})
            self.client.post(reverse("form_scan:upload"), {"photo": [upload(color=(3, 2, 1))], "target": "CROP", "consent": "1"})
        warnings = ActivityLog.objects.filter(title="Daily Scan Limit Reached")
        self.assertEqual(warnings.count(), 1)
        self.assertEqual(warnings.get().status, "Warning")
        recipients = set(Notification.objects.filter(source_activity=warnings.get()).values_list("recipient__role", flat=True))
        self.assertEqual(recipients, {"ADMIN"})  # administrators only, never other staff
        self.assertTrue(Notification.objects.filter(recipient=self.office_admin, source_activity=warnings.get()).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.other_staff, source_activity=warnings.get()).exists())

    def test_every_model_failing_warns_administrators(self):
        from unittest import mock

        providers = {"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "MODELS": ["m1"], "DAILY_LIMIT": 30}
        with override_settings(OCR=providers), mock.patch("apps.ocr.providers.requests.post", return_value=mock.Mock(status_code=500)):
            self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL", "consent": "1"})
        self.assertTrue(ActivityLog.objects.filter(title="Form Reader Not Responding", status="Warning").exists())

    def test_the_activity_log_page_lists_the_module_for_filtering(self):
        self.client.post(reverse("form_scan:upload"), {"photo": [upload()], "target": "PARCEL"})
        self.client.force_login(self.office_admin)
        page = self.client.get(reverse("activity_logs:list"), {"module": "Scan & Auto-Fill"})
        self.assertContains(page, "Form Scanned")
        self.assertIn("Scan & Auto-Fill", list(page.context["modules"]))


class FarmerScanAuditTests(ScanTestCase):
    def setUp(self):
        self.client.force_login(self.staff)

    @override_settings(RSBSA_SCAN_ENGINE="ocr")
    def test_reading_a_form_logs_a_scan_not_a_farmer_creation(self):
        result = self.client.post(reverse("farmers:scan_rsbsa"), {"rsbsa_scan": upload(color=(5, 90, 90))})
        self.assertEqual(result.status_code, 200)
        titles = list(ActivityLog.objects.values_list("title", flat=True))
        self.assertEqual(titles, ["Form Scanned"])
        event = ActivityLog.objects.get()
        self.assertIn("Farmer Registration form", event.description)
        self.assertIn("No photo was stored", event.description)
        self.assertFalse(FormScan.objects.exists())

    def test_the_review_outcome_is_logged_with_field_names_only(self):
        body = {"applied": ["last_name", "barangay", "not_a_field"], "kept": ["phone_number"], "skipped": ["sex"]}
        response = self.client.post(reverse("farmers:scan_rsbsa_applied"), json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        event = ActivityLog.objects.get(title="Scan Reviewed")
        self.assertIn("2 applied, 1 kept as typed, 1 skipped", event.description)
        self.assertEqual({d["field"]: d["after"] for d in event.details}["Applied"], "last_name, barangay")
        self.assertNotIn("not_a_field", json.dumps(event.details))

    def test_closing_the_review_without_applying_is_logged(self):
        self.client.post(reverse("farmers:scan_rsbsa_applied"), json.dumps({"cancelled": True}), content_type="application/json")
        self.assertIn("without applying", ActivityLog.objects.get(title="Scan Reviewed").description)

    def test_bad_requests_are_refused(self):
        self.assertEqual(self.client.post(reverse("farmers:scan_rsbsa_applied"), "not json", content_type="application/json").status_code, 400)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("farmers:scan_rsbsa_applied"), "{}", content_type="application/json").status_code, 302)
