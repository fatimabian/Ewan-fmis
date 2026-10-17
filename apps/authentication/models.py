from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.common.constants import ROLE_ADMIN, ROLE_CHOICES


class CustomUser(AbstractUser):
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default="STAFF")
    phone_number = models.CharField(max_length=20, blank=True)
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)
    activation_pending = models.BooleanField(
        default=False,
        help_text="New staff account must verify its email OTP before first access.",
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_username = models.CharField(max_length=150, blank=True)
    deleted_display_name = models.CharField(max_length=255, blank=True)

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
