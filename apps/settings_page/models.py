from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("system", "System")]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences")
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default="light")
    primary_color = models.CharField(max_length=7, default="#008552")
    email_notifications = models.BooleanField(default=True)
    in_app_notifications = models.BooleanField(default=True)
    weekly_summary = models.BooleanField(default=True)
    two_factor_enabled = models.BooleanField(default=False)
    linked_email = models.EmailField(blank=True)

    def __str__(self):
        return f"Preferences for {self.user}"


class SystemSetting(models.Model):
    """Single shared configuration record for the FMIS administrator."""

    system_name = models.CharField(max_length=150, default="FMIS - Office of Agriculture")
    timezone = models.CharField(max_length=100, default="Asia/Manila")
    default_language = models.CharField(max_length=30, default="English")
    session_timeout = models.PositiveIntegerField(default=15)
    automated_backups = models.BooleanField(default=True)
    two_factor_required = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        setting, _ = cls.objects.get_or_create(pk=1)
        return setting
