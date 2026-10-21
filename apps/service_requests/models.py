from django.conf import settings
from django.db import models
from apps.farmers.models import Farmer
from apps.service_catalog.models import ServiceCatalog


class ServiceRequest(models.Model):
    SCOPE_CHOICES = [
        ("INDIVIDUAL", "One farmer"),
        ("BARANGAY", "Barangay"),
    ]
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("IN_PROGRESS", "In Progress"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    ]
    PRIORITY_CHOICES = [("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")]
    scope = models.CharField(max_length=12, choices=SCOPE_CHOICES, default="INDIVIDUAL")
    farmer = models.ForeignKey(
        Farmer,
        on_delete=models.PROTECT,
        related_name="service_requests",
        null=True,
        blank=True,
    )
    target_barangay = models.CharField(max_length=100, blank=True)
    service = models.ForeignKey(ServiceCatalog, on_delete=models.PROTECT)
    subject = models.CharField(max_length=180, default="Agricultural service request")
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="MEDIUM")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    notes = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        scope="INDIVIDUAL",
                        farmer__isnull=False,
                        target_barangay="",
                    )
                    | (
                        models.Q(scope="BARANGAY", farmer__isnull=True)
                        & ~models.Q(target_barangay="")
                    )
                ),
                name="service_request_scope_target_valid",
            )
        ]

    @property
    def request_id(self):
        return f"SR-{self.pk:04d}" if self.pk else "New"

    @property
    def beneficiary_label(self):
        if self.scope == "BARANGAY":
            return f"All active farmers in Brgy. {self.target_barangay}"
        if self.farmer_id:
            return self.farmer.list_name
        return "Beneficiary not specified"

    @property
    def beneficiary_reference(self):
        return self.farmer.record_id if self.farmer_id else "Barangay"

    def __str__(self):
        return f"{self.request_id} - {self.subject}"


class ServiceRequestHistory(models.Model):
    ACTION_CHOICES = [
        ("CREATED", "Created"),
        ("UPDATED", "Updated"),
        ("CANCELLED", "Cancelled"),
        ("REOPENED", "Reopened"),
    ]

    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.CASCADE,
        related_name="history",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="service_request_updates",
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    changes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.service_request.request_id} - {self.get_action_display()}"
