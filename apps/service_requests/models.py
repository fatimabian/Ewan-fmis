from django.conf import settings
from django.db import models
from apps.farmers.models import Farmer
from apps.service_catalog.models import ServiceCatalog


class ServiceRequest(models.Model):
    STATUS_CHOICES = [("PENDING", "Pending"), ("IN_PROGRESS", "In Progress"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")]
    PRIORITY_CHOICES = [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")]
    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="service_requests")
    service = models.ForeignKey(ServiceCatalog, on_delete=models.PROTECT)
    subject = models.CharField(max_length=180, default="Agricultural service request")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="MEDIUM")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def request_id(self):
        return f"SR-{self.pk:04d}" if self.pk else "New"

    def __str__(self):
        return f"{self.request_id} - {self.subject}"
