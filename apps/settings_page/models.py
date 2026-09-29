from django.conf import settings
from django.db import models


class UserPreference(models.Model):
    THEME_CHOICES = [("light", "Light"), ("dark", "Dark"), ("system", "System")]
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences"
    )
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default="system")
    primary_color = models.CharField(max_length=7, default="#008552")
    in_app_notifications = models.BooleanField(default=True)
    linked_email = models.EmailField(blank=True)
    profile_photo = models.ImageField(upload_to="account_profiles/", blank=True)

    def __str__(self):
        return f"Preferences for {self.user}"


class SystemSetting(models.Model):
    """Single shared configuration record for the FMIS administrator."""

    system_name = models.CharField(max_length=150, default="FMIS - Office of Agriculture")
    timezone = models.CharField(max_length=100, default="Asia/Manila")
    default_language = models.CharField(max_length=30, default="English")
    session_timeout = models.PositiveIntegerField(default=15)
    automated_backups = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        setting, _ = cls.objects.get_or_create(pk=1)
        return setting


class BackupRun(models.Model):
    STATUS_CHOICES = [
        ("RUNNING", "In progress"),
        ("VERIFIED", "Verified"),
        ("FAILED", "Needs attention"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="RUNNING")
    storage = models.CharField(max_length=100, blank=True)
    archive_name = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True)
    offsite = models.BooleanField(default=False)
    media_files = models.PositiveIntegerField(default=0)
    retained_copies = models.PositiveIntegerField(default=0)
    error_message = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at", "-pk"]
