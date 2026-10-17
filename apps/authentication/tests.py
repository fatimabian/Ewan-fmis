import re
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.authentication.activation import ACTIVATION_SESSION_KEY
from apps.authentication.mfa import (
    encrypt_secret,
    hash_recovery_codes,
    totp_at,
)


class AccountActivationDeliveryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pendingdelivery",
            email="pending@example.com",
            password="Ready4Field!Secure",
            role="STAFF",
            is_active=False,
            activation_pending=True,
        )

    @patch("apps.authentication.activation.EmailMultiAlternatives.send", return_value=0)
    def test_rejected_activation_email_does_not_leave_a_valid_challenge(self, _send):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": "Ready4Field!Secure"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The activation email could not be sent")
        self.assertNotIn(ACTIVATION_SESSION_KEY, self.client.session)


class PasswordRecoveryOTPTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="recoverystaff",
            email="recovery@example.com",
            password="Old-password-482!",
            is_active=True,
        )
        self.url = reverse("authentication:password_reset")

    def test_email_otp_verification_is_required_before_password_change(self):
        requested = self.client.post(
            self.url,
            {"recovery_action": "request", "identifier": self.user.email},
        )
        self.assertEqual(requested.status_code, 200)
        self.assertContains(requested, "Enter your email OTP")
        self.assertEqual(len(mail.outbox), 1)
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)

        blocked = self.client.post(
            self.url,
            {
                "recovery_action": "reset",
                "new_password1": "New-password-593!",
                "new_password2": "New-password-593!",
            },
        )
        self.assertEqual(blocked.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Old-password-482!"))

        # Request a fresh challenge because the blocked reset deliberately clears it.
        self.client.post(
            self.url,
            {"recovery_action": "request", "identifier": self.user.email},
        )
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        verified = self.client.post(
            self.url,
            {"recovery_action": "verify", "code": code},
        )
        self.assertEqual(verified.status_code, 200)
        self.assertContains(verified, "Create a new password")

        changed = self.client.post(
            self.url,
            {
                "recovery_action": "reset",
                "new_password1": "New-password-593!",
                "new_password2": "New-password-593!",
            },
        )
        self.assertRedirects(changed, reverse("authentication:login"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("New-password-593!"))

    def test_unknown_identifier_uses_same_otp_screen_without_sending_email(self):
        response = self.client.post(
            self.url,
            {"recovery_action": "request", "identifier": "unknown@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter your email OTP")
        self.assertContains(response, "the registered email address")
        self.assertEqual(len(mail.outbox), 0)


@override_settings(FMIS_REQUIRE_MFA=True)
class MultiFactorAuthenticationTests(TestCase):
    password = "Ready4Field!Secure"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="mfastaff",
            email="mfastaff@example.com",
            password=self.password,
            role="STAFF",
            is_active=True,
        )

    def _start_login(self, client=None):
        client = client or self.client
        return client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": self.password},
        )

    def _enroll(self):
        response = self._start_login()
        self.assertRedirects(response, reverse("authentication:mfa_setup"))
        setup = self.client.get(reverse("authentication:mfa_setup"))
        self.assertContains(setup, "Set up your authenticator")
        secret = self.client.session["fmis_mfa_setup_secret"]
        code = totp_at(secret, int(time.time() // 30))
        response = self.client.post(reverse("authentication:mfa_setup"), {"code": code})
        self.assertRedirects(response, reverse("authentication:mfa_recovery_codes"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)
        self.assertNotEqual(self.user.mfa_secret, secret)
        self.assertEqual(len(self.user.mfa_recovery_codes), 10)
        return secret

    def test_first_password_login_requires_authenticator_enrollment(self):
        self._enroll()
        response = self.client.get(reverse("authentication:mfa_recovery_codes"))
        self.assertContains(response, "Save your recovery codes")
        self.assertContains(response, "I Have Saved These Codes")
        response = self.client.post(reverse("authentication:mfa_recovery_codes"))
        self.assertRedirects(response, reverse("dashboard:staff_home"))

    def test_email_activation_continues_to_authenticator_enrollment(self):
        pending = get_user_model().objects.create_user(
            username="newfieldstaff",
            email="newfieldstaff@example.com",
            password=self.password,
            role="STAFF",
            is_active=False,
            activation_pending=True,
        )
        response = self.client.post(
            reverse("authentication:login"),
            {"username": pending.username, "password": self.password},
        )
        self.assertRedirects(response, reverse("authentication:activate_account"))
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        response = self.client.post(
            reverse("authentication:activate_account"), {"code": code}
        )
        self.assertRedirects(response, reverse("authentication:mfa_setup"))
        pending.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertFalse(pending.activation_pending)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_totp_matches_rfc_6238_sha1_vector_truncated_to_six_digits(self):
        # RFC 6238 uses this 20-byte secret and expects 94287082 at 59 seconds.
        # The FMIS six-digit profile is the final six digits of the same value.
        self.assertEqual(
            totp_at("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 1),
            "287082",
        )

    def test_enrolled_user_must_supply_fresh_totp(self):
        secret = "JBSWY3DPEHPK3PXP"
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret(secret)
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])

        response = self._start_login()
        self.assertRedirects(response, reverse("authentication:mfa_verify"))
        self.assertNotIn("_auth_user_id", self.client.session)

        counter = int(time.time() // 30)
        code = totp_at(secret, counter)
        response = self.client.post(reverse("authentication:mfa_verify"), {"code": code})
        self.assertRedirects(response, reverse("dashboard:staff_home"))
        self.assertIn("_auth_user_id", self.client.session)

        self.client.post(reverse("authentication:logout"))
        self._start_login()
        replay = self.client.post(reverse("authentication:mfa_verify"), {"code": code})
        self.assertEqual(replay.status_code, 200)
        self.assertContains(replay, "invalid, expired, or already used")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_recovery_code_is_consumed_after_one_use(self):
        secret = "JBSWY3DPEHPK3PXP"
        recovery_code = "ABCDE-23456"
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret(secret)
        self.user.mfa_recovery_codes = hash_recovery_codes([recovery_code])
        self.user.save(
            update_fields=["mfa_enabled", "mfa_secret", "mfa_recovery_codes"]
        )
        self._start_login()
        response = self.client.post(
            reverse("authentication:mfa_verify"), {"code": recovery_code}
        )
        self.assertRedirects(response, reverse("dashboard:staff_home"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.mfa_recovery_codes, [])

    def test_admin_reset_revokes_existing_session_and_requires_reenrollment(self):
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])
        staff_client = Client()
        staff_client.force_login(self.user)
        admin = get_user_model().objects.create_user(
            username="securityadmin",
            password=self.password,
            role="ADMIN",
            is_active=True,
        )
        self.client.force_login(admin)
        response = self.client.post(reverse("accounts:reset_mfa", args=[self.user.pk]))
        self.assertRedirects(response, reverse("accounts:edit", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)
        self.assertEqual(self.user.mfa_secret, "")
        revoked = staff_client.get(reverse("dashboard:staff_home"))
        self.assertEqual(revoked.status_code, 302)
        self.assertTrue(revoked.url.startswith(reverse("authentication:login")))
