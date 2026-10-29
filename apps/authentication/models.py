from django.contrib.auth.models import AbstractUser
from django.utils.crypto import salted_hmac
from django.db import models
from apps.common.constants import ROLE_ADMIN, ROLE_CHOICES


class CustomUser(AbstractUser):
    APPROVAL_PENDING = "PENDING"
    APPROVAL_APPROVED = "APPROVED"
    APPROVAL_REJECTED = "REJECTED"
    APPROVAL_CHOICES = [
        (APPROVAL_PENDING, "Pending administrator approval"),
        (APPROVAL_APPROVED, "Approved"),
        (APPROVAL_REJECTED, "Rejected"),
    ]
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default="STAFF")
    phone_number = models.CharField(max_length=20, blank=True)
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)
    activation_pending = models.BooleanField(
        default=False,
        help_text="New staff account must verify its email OTP before first access.",
    )
    approval_status = models.CharField(
        max_length=12,
        choices=APPROVAL_CHOICES,
        default=APPROVAL_APPROVED,
        db_index=True,
    )
    approval_reviewed_at = models.DateTimeField(null=True, blank=True)
    approval_reviewed_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_staff_registrations",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_username = models.CharField(max_length=150, blank=True)
    deleted_display_name = models.CharField(max_length=255, blank=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.TextField(blank=True)
    mfa_recovery_codes = models.JSONField(default=list, blank=True)
    mfa_last_counter = models.BigIntegerField(null=True, blank=True)
    mfa_version = models.PositiveIntegerField(default=0)

    @property
    def is_admin(self):
        return self.is_superuser or self.role == ROLE_ADMIN

    @property
    def display_name(self):
        return self.deleted_display_name or self.get_full_name() or self.username

    @property
    def audit_username(self):
        return self.deleted_username or self.username

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def get_session_auth_hash(self):
        """Invalidate every session when an administrator resets MFA."""
        password_hash = super().get_session_auth_hash()
        return salted_hmac(
            "authentication.CustomUser.session",
            f"{password_hash}:{self.mfa_version}",
        ).hexdigest()
