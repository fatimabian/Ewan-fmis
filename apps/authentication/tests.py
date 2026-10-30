import re
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.authentication.activation import ACTIVATION_SESSION_KEY
from apps.authentication.mfa import (
    MFA_SESSION_KEY,
    TRUSTED_DEVICE_COOKIE,
    encrypt_secret,
    hash_recovery_codes,
    totp_at,
)


@override_settings(FMIS_REQUIRE_MFA=False)
class StaffRegistrationApprovalTests(TestCase):
    password = "Ready4Field!Secure"

    def registration_data(self, **overrides):
        data = {
            "username": "new-oas-staff",
            "first_name": "Maria",
            "last_name": "Santos",
            "email": "maria.santos@example.com",
            "phone_number": "09171234567",
            "password1": self.password,
            "password2": self.password,
        }
        data.update(overrides)
        return data

    def test_registration_requires_admin_approval_before_activation(self):
        response = self.client.post(
            reverse("authentication:register_staff"), self.registration_data()
        )
        self.assertRedirects(response, reverse("authentication:login"))
        account = get_user_model().objects.get(username="new-oas-staff")
        self.assertEqual(account.role, "STAFF")
        self.assertEqual(account.approval_status, account.APPROVAL_PENDING)
        self.assertFalse(account.is_active)
        self.assertFalse(account.activation_pending)

        login_response = self.client.post(
            reverse("authentication:login"),
            {"username": account.username, "password": self.password},
        )
        self.assertContains(login_response, "awaiting administrator approval")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_approval_enables_email_verification_not_immediate_access(self):
        account = get_user_model().objects.create_user(
            username="pending-review",
            password=self.password,
            email="pending-review@example.com",
            phone_number="09171234568",
            role="STAFF",
            is_active=False,
            activation_pending=False,
            approval_status="PENDING",
        )
        admin = get_user_model().objects.create_user(
            username="registration-admin",
            password=self.password,
            role="ADMIN",
            is_active=True,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("accounts:review", args=[account.pk]), {"action": "approve"}
        )
        self.assertRedirects(response, reverse("accounts:list"))
        account.refresh_from_db()
        self.assertEqual(account.approval_status, account.APPROVAL_APPROVED)
        self.assertFalse(account.is_active)
        self.assertTrue(account.activation_pending)
        self.assertEqual(account.approval_reviewed_by, admin)
        self.assertIsNotNone(account.approval_reviewed_at)

    def test_rejected_registration_cannot_be_reactivated_through_account_toggle(self):
        account = get_user_model().objects.create_user(
            username="rejected-review",
            password=self.password,
            role="STAFF",
            is_active=False,
            approval_status="REJECTED",
        )
        admin = get_user_model().objects.create_user(
            username="rejection-admin",
            password=self.password,
            role="ADMIN",
            is_active=True,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("accounts:delete", args=[account.pk]), {"action": "restore"}
        )
        self.assertRedirects(response, reverse("accounts:list"))
        account.refresh_from_db()
        self.assertFalse(account.is_active)
        self.assertEqual(account.approval_status, account.APPROVAL_REJECTED)


@override_settings(FMIS_REQUIRE_MFA=False)
class DisabledMultiFactorAuthenticationTests(TestCase):
    password = "Ready4Field!Secure"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="passwordonlystaff",
            email="passwordonly@example.com",
            password=self.password,
            role="STAFF",
            is_active=True,
            mfa_enabled=True,
            mfa_secret=encrypt_secret("JBSWY3DPEHPK3PXP"),
        )

    def test_password_login_bypasses_dormant_mfa_enrollment(self):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": self.password},
        )
        self.assertRedirects(response, reverse("dashboard:staff_home"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_stale_mfa_setup_session_returns_to_login(self):
        session = self.client.session
        session[MFA_SESSION_KEY] = {
            "user_id": self.user.pk,
            "remember_me": False,
            "next_url": "",
            "started_at": int(time.time()),
        }
        session["fmis_mfa_setup_secret"] = "EXPOSEDSECRET"
        session.save()

        response = self.client.get(reverse("authentication:mfa_setup"))

        self.assertRedirects(response, reverse("authentication:login"))
        self.assertNotIn(MFA_SESSION_KEY, self.client.session)
        self.assertNotIn("fmis_mfa_setup_secret", self.client.session)


class AccountActivationDeliveryTests(TestCase):
    def setUp(self):
        cache.clear()
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

    def test_activation_email_contains_exactly_one_code(self):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": "Ready4Field!Secure"},
        )

        self.assertRedirects(response, reverse("authentication:activate_account"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "FMIS — Your Verification Code")
        self.assertEqual(len(re.findall(r"\b\d{6}\b", mail.outbox[0].body)), 1)

    def test_replayed_login_reuses_active_code_across_browser_sessions(self):
        payload = {"username": self.user.username, "password": "Ready4Field!Secure"}
        second_browser = Client()

        first = self.client.post(reverse("authentication:login"), payload)
        replay = second_browser.post(reverse("authentication:login"), payload)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(ACTIVATION_SESSION_KEY, second_browser.session)

    def test_rapid_resend_keeps_current_code_and_sends_no_second_email(self):
        self.client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": "Ready4Field!Secure"},
        )

        response = self.client.post(
            reverse("authentication:activate_account"), {"action": "resend"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wait 60 seconds")
        self.assertEqual(len(mail.outbox), 1)

    @patch("apps.authentication.activation.cache.add", return_value=False)
    def test_issue_lock_blocks_concurrent_duplicate_send(self, _add):
        response = self.client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": "Ready4Field!Secure"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "activation email could not be sent")
        self.assertEqual(len(mail.outbox), 0)

    def test_activation_form_has_single_submit_guard(self):
        self.client.post(
            reverse("authentication:login"),
            {"username": self.user.username, "password": "Ready4Field!Secure"},
        )

        response = self.client.get(reverse("authentication:activate_account"))

        self.assertContains(response, "data-single-submit")
        self.assertContains(response, "single-submit.min.")


class PasswordRecoveryOTPTests(TestCase):
    def setUp(self):
        cache.clear()
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
        self.assertEqual(self.user.mfa_version, 1)

    def test_unknown_identifier_uses_same_otp_screen_without_sending_email(self):
        response = self.client.post(
            self.url,
            {"recovery_action": "request", "identifier": "unknown@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enter your email OTP")
        self.assertContains(response, "the registered email address")
        self.assertEqual(len(mail.outbox), 0)

    def test_repeated_request_reuses_active_code_and_sends_one_email(self):
        payload = {"recovery_action": "request", "identifier": self.user.email}

        first = self.client.post(self.url, payload)
        second = self.client.post(self.url, payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "Enter your email OTP")
        self.assertEqual(len(mail.outbox), 1)

    def test_replayed_recovery_request_across_browsers_sends_one_email(self):
        payload = {"recovery_action": "request", "identifier": self.user.email}
        second_browser = Client()

        first = self.client.post(self.url, payload)
        replay = second_browser.post(self.url, payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "FMIS — Your Verification Code")
        self.assertEqual(len(re.findall(r"\b\d{6}\b", mail.outbox[0].body)), 1)


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
        self.assertNotContains(setup, "Authenticator setup QR code")
        response = self.client.post(
            reverse("authentication:mfa_setup"),
            {"current_password": self.password},
        )
        self.assertRedirects(response, reverse("authentication:mfa_setup"))
        secret = self.client.session["fmis_mfa_setup_secret"]
        code = totp_at(secret, int(time.time() // 30))
        response = self.client.post(
            reverse("authentication:mfa_setup"),
            {"code": code},
        )
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

    def test_authenticator_setup_requires_password_reentry(self):
        self._start_login()
        setup = self.client.get(reverse("authentication:mfa_setup"))
        self.assertNotContains(setup, "Authenticator setup QR code")
        self.assertNotIn("fmis_mfa_setup_secret", self.client.session)
        response = self.client.post(
            reverse("authentication:mfa_setup"),
            {"current_password": "wrong password"},
        )
        self.assertContains(response, "password is incorrect")
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)

    def test_new_account_challenge_discards_prior_setup_secret_and_authorization(self):
        self._start_login()
        self.client.post(
            reverse("authentication:mfa_setup"),
            {"current_password": self.password},
        )
        self.client.get(reverse("authentication:mfa_setup"))
        first_secret = self.client.session["fmis_mfa_setup_secret"]

        second_user = get_user_model().objects.create_user(
            username="secondmfastaff",
            email="secondmfastaff@example.com",
            password=self.password,
            role="STAFF",
            is_active=True,
        )
        response = self.client.post(
            reverse("authentication:login"),
            {"username": second_user.username, "password": self.password},
        )
        self.assertRedirects(response, reverse("authentication:mfa_setup"))
        self.assertNotIn("fmis_mfa_setup_secret", self.client.session)
        self.assertNotIn("fmis_mfa_password_confirmed", self.client.session)

        self.client.post(
            reverse("authentication:mfa_setup"),
            {"current_password": self.password},
        )
        self.client.get(reverse("authentication:mfa_setup"))
        self.assertNotEqual(first_secret, self.client.session["fmis_mfa_setup_secret"])

    def test_setup_qr_cannot_be_reopened_after_activation(self):
        self._enroll()
        self.client.post(reverse("authentication:mfa_recovery_codes"))
        response = self.client.get(reverse("authentication:mfa_setup"))
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

    def test_trusted_private_browser_skips_mfa_for_later_password_login(self):
        secret = "JBSWY3DPEHPK3PXP"
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret(secret)
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])
        self._start_login()
        code = totp_at(secret, int(time.time() // 30))
        verified = self.client.post(
            reverse("authentication:mfa_verify"),
            {"code": code, "trust_device": "on"},
        )
        self.assertRedirects(verified, reverse("dashboard:staff_home"))
        trusted_cookie = verified.cookies[TRUSTED_DEVICE_COOKIE]
        self.assertTrue(trusted_cookie["httponly"])
        self.assertEqual(trusted_cookie["samesite"], "Lax")
        self.assertEqual(int(trusted_cookie["max-age"]), 30 * 24 * 60 * 60)

        self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        later_login = self._start_login()
        self.assertRedirects(later_login, reverse("dashboard:staff_home"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_tampered_or_reset_trusted_browser_requires_mfa_again(self):
        secret = "JBSWY3DPEHPK3PXP"
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret(secret)
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])
        self._start_login()
        code = totp_at(secret, int(time.time() // 30))
        response = self.client.post(
            reverse("authentication:mfa_verify"),
            {"code": code, "trust_device": "on"},
        )
        self.assertIn(TRUSTED_DEVICE_COOKIE, response.cookies)
        valid_cookie_value = response.cookies[TRUSTED_DEVICE_COOKIE].value

        self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        self.client.cookies[TRUSTED_DEVICE_COOKIE] = valid_cookie_value + "tampered"
        response = self._start_login()
        self.assertRedirects(response, reverse("authentication:mfa_verify"))

        self.client.cookies[TRUSTED_DEVICE_COOKIE] = valid_cookie_value
        self.user.mfa_version += 1
        self.user.save(update_fields=["mfa_version"])
        self.client.cookies.pop(settings.SESSION_COOKIE_NAME, None)
        response = self._start_login()
        self.assertRedirects(response, reverse("authentication:mfa_verify"))

    def test_manual_logout_forgets_the_trusted_browser(self):
        secret = "JBSWY3DPEHPK3PXP"
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret(secret)
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])
        self._start_login()
        response = self.client.post(
            reverse("authentication:mfa_verify"),
            {
                "code": totp_at(secret, int(time.time() // 30)),
                "trust_device": "on",
            },
        )
        self.assertIn(TRUSTED_DEVICE_COOKIE, response.cookies)
        logout_response = self.client.post(reverse("authentication:logout"))
        self.assertEqual(logout_response.cookies[TRUSTED_DEVICE_COOKIE]["max-age"], 0)
        response = self._start_login()
        self.assertRedirects(response, reverse("authentication:mfa_verify"))

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
        admin_secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        admin.mfa_enabled = True
        admin.mfa_secret = encrypt_secret(admin_secret)
        admin.save(update_fields=["mfa_enabled", "mfa_secret"])
        self.client.force_login(admin)
        response = self.client.post(
            reverse("accounts:reset_mfa", args=[self.user.pk]),
            {
                "current_password": self.password,
                "code": totp_at(admin_secret, int(time.time() // 30)),
            },
        )
        self.assertRedirects(response, reverse("accounts:edit", args=[self.user.pk]))
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)
        self.assertEqual(self.user.mfa_secret, "")
        revoked = staff_client.get(reverse("dashboard:staff_home"))
        self.assertEqual(revoked.status_code, 302)
        self.assertTrue(revoked.url.startswith(reverse("authentication:login")))

    def test_admin_cannot_reset_another_authenticator_without_reverification(self):
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])
        admin = get_user_model().objects.create_user(
            username="otheradmin", password=self.password, role="ADMIN", is_active=True,
            mfa_enabled=True, mfa_secret=encrypt_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"),
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("accounts:reset_mfa", args=[self.user.pk]),
            {"current_password": "wrong", "code": "000000"},
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)

    def test_staff_cannot_open_another_accounts_authenticator_reset(self):
        self.user.mfa_enabled = True
        self.user.mfa_secret = encrypt_secret("JBSWY3DPEHPK3PXP")
        self.user.save(update_fields=["mfa_enabled", "mfa_secret"])
        other_staff = get_user_model().objects.create_user(
            username="ordinaryfieldstaff",
            password=self.password,
            role="STAFF",
            is_active=True,
        )
        self.client.force_login(other_staff)
        response = self.client.get(reverse("accounts:reset_mfa", args=[self.user.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("dashboard:home"))
