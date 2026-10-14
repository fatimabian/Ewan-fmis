import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.authentication.activation import ACTIVATION_SESSION_KEY


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
