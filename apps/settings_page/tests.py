"""Recovery authorization, archive validation, and dated backup downloads."""
import base64
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.common.backups import create_verified_backup, verify_existing_backup


class RecoveryWorkflowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_user(username="recovery-admin", password="Test-only-Password-28!", role="ADMIN")
        self.staff = get_user_model().objects.create_user(username="recovery-staff", role="STAFF")
        self.client.force_login(self.admin)
        self.url = reverse("settings_page:prepare_restore")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings_override = override_settings(
            BACKUP_ROOT=Path(self.directory.name),
            FMIS_BACKUP_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"r" * 32).decode(),
            BACKUP_AZURE_CONTAINER_URL="", BACKUP_RCLONE_REMOTE="",
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def unlock(self):
        response = self.client.post(self.url, {"restore_action": "unlock", "restore_password": "Test-only-Password-28!"})
        self.assertEqual(response.status_code, 200)
        return response.json()["token"]

    def upload(self, token, contents=b"invalid archive"):
        return self.client.post(self.url, {"restore_token": token, "restore_archive": SimpleUploadedFile("backup.fmisbak", contents)})

    def test_blank_and_incorrect_password_errors_are_field_errors(self):
        for password, expected in (("", "Enter your administrator password."), ("wrong", "Your administrator password is incorrect.")):
            response = self.client.post(self.url, {"restore_action": "unlock", "restore_password": password})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["errors"]["restore_password"], expected)
        self.assertNotIn("restore_authorization", self.client.session)
        self.assertFalse(list(Path(self.directory.name).iterdir()))

    def test_upload_cannot_bypass_password_gate(self):
        response = self.upload("forged-token")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(list(Path(self.directory.name).iterdir()))

    def test_expired_and_wrong_tokens_are_rejected(self):
        token = self.unlock()
        response = self.upload("wrong-token")
        self.assertEqual(response.status_code, 403)
        token = self.unlock()
        session = self.client.session
        session["restore_authorization"] = {**session["restore_authorization"], "expires": 1}
        session.save()
        self.assertEqual(self.upload(token).status_code, 403)

    def test_password_attempts_are_limited(self):
        for _ in range(5):
            self.client.post(self.url, {"restore_action": "unlock", "restore_password": "wrong"})
        response = self.client.post(self.url, {"restore_action": "unlock", "restore_password": "Test-only-Password-28!"})
        self.assertEqual(response.status_code, 429)

    def test_invalid_archive_removed_without_reporting_success(self):
        response = self.upload(self.unlock())
        self.assertEqual(response.status_code, 400)
        self.assertIn("restore_archive", response.json()["errors"])
        self.assertFalse(list(Path(self.directory.name).rglob("*.fmisbak")))

    def test_verified_package_and_single_use_authorization(self):
        backup = create_verified_backup()
        contents = backup.path.read_bytes()
        token = self.unlock()
        response = self.upload(token, contents)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("No live records were changed", response.json()["message"])
        staged = list((Path(self.directory.name) / "restore-staging").glob("*.fmisbak"))
        self.assertEqual(len(staged), 1)
        self.assertEqual(verify_existing_backup(staged[0]), backup.checksum)
        self.assertEqual(staged[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.upload(token, contents).status_code, 403)
        self.assertTrue(get_user_model().objects.filter(pk=self.admin.pk).exists())

    def test_staff_cannot_unlock_or_download_backup(self):
        self.client.force_login(self.staff)
        for url in (self.url, reverse("settings_page:manual_backup")):
            response = self.client.post(url, {"restore_action": "unlock", "restore_password": "anything"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("dashboard:home"))

    def test_backup_download_is_dated_verified_and_private(self):
        response = self.client.post(reverse("settings_page:manual_backup"))
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response["Content-Disposition"], r'fmis-backup-\d{4}-\d{2}-\d{2}_')
        self.assertEqual(response["Cache-Control"], "private, no-store")
        data = b"".join(response.streaming_content)
        response.close()
        archive = next(Path(self.directory.name).glob("*.fmisbak"))
        self.assertEqual(data, archive.read_bytes())
        verify_existing_backup(archive)

    def test_csrf_protects_password_unlock(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        response = client.post(self.url, {"restore_action": "unlock", "restore_password": "Test-only-Password-28!"})
        self.assertEqual(response.status_code, 403)


class InlineCredentialTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_blank_credentials_render_beneath_fields(self):
        response = self.client.post(reverse("authentication:login"), {"username": "", "password": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIn("username", response.context["form"].errors)
        self.assertIn("password", response.context["form"].errors)
        self.assertContains(response, 'aria-invalid="true"', count=2)
        self.assertNotContains(response, 'data-feedback-message')

    def test_wrong_credentials_stay_inline(self):
        response = self.client.post(reverse("authentication:login"), {"username": "missing-user", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<small class="landing-field-error">The username or password is incorrect.</small>', html=True)
        self.assertNotContains(response, 'data-feedback-message')
