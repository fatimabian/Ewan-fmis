from django.conf import settings
from django.db import models


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    source_activity = models.ForeignKey(
        "activity_logs.ActivityLog",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=150)
    message = models.CharField(max_length=255)
    category = models.CharField(max_length=40, default="system")
    url = models.CharField(max_length=500, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=("recipient", "source_activity"),
                name="unique_notification_recipient_activity",
            )
        ]

    def __str__(self):
        return f"{self.title} for {self.recipient}"
