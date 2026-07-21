from django.contrib.auth.models import AbstractUser
from django.db import models
from apps.common.constants import ROLE_ADMIN, ROLE_CHOICES


class CustomUser(AbstractUser):
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default="STAFF")
    phone_number = models.CharField(max_length=20, blank=True)
    google_sub = models.CharField(max_length=255, unique=True, null=True, blank=True)

    @property
    def is_admin(self):
        return self.is_superuser or self.role == ROLE_ADMIN

    @property
    def display_name(self):
        return self.get_full_name() or self.username
