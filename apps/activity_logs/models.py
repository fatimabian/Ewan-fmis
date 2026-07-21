from django.conf import settings
from django.db import models
class ActivityLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=255)
    path = models.CharField(max_length=255)
    title = models.CharField(max_length=150, blank=True)
    description = models.CharField(max_length=255, blank=True)
    module = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, default="Success")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ["-created_at"]
