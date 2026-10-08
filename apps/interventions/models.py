from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest


class Intervention(models.Model):
    SCOPE_CHOICES = [
        ("INDIVIDUAL", "One farmer"),
        ("SELECTED", "Selected farmers"),
        ("BARANGAY", "All active farmers in a barangay"),
        ("ALL", "All active farmers"),
    ]
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SCHEDULED", "Scheduled"),
        ("ONGOING", "Ongoing"),
        ("COMPLETED", "Completed"),
        ("CANCELLED", "Cancelled"),
    ]
    TYPE_CHOICES = [
        ("SEEDS", "Seeds / planting materials"),
        ("FERTILIZER", "Fertilizer / soil inputs"),
        ("EQUIPMENT", "Equipment / machinery support"),
        ("TRAINING", "Training / seminar"),
        ("TECHNICAL", "Technical assistance"),
        ("FINANCIAL", "Financial assistance"),
        ("LIVESTOCK", "Livestock / poultry support"),
        ("OTHER", "Other intervention"),
    ]

    farmer = models.ForeignKey(
        Farmer, on_delete=models.PROTECT, related_name="interventions", null=True, blank=True
    )
    scope = models.CharField(max_length=12, choices=SCOPE_CHOICES, default="INDIVIDUAL")
    target_barangay = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="COMPLETED")
    service_request = models.ForeignKey(
        ServiceRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interventions",
    )
    intervention_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    intervention_date = models.DateField()
    description = models.CharField(max_length=240)
    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    unit = models.CharField(max_length=40, blank=True)
    estimated_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    funding_source = models.CharField(max_length=160, blank=True)
    provider = models.CharField(max_length=160, default="Office for Agricultural Services")
    remarks = models.TextField(blank=True, max_length=1000)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_interventions",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-intervention_date", "-pk"]

    @property
    def reference_id(self):
        return f"INT-{self.pk:04d}" if self.pk else "New"

    def __str__(self):
        return f"{self.reference_id} - {self.beneficiary_label}"

    @property
    def beneficiary_label(self):
        if self.scope == "INDIVIDUAL" and self.farmer_id:
            return self.farmer.list_name
        if self.scope == "BARANGAY":
            return f"{self.target_barangay} farmers"
        return self.get_scope_display()


class InterventionRecipient(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("RECEIVED", "Received"),
        ("DECLINED", "Declined"),
        ("NO_SHOW", "No-show"),
    ]

    intervention = models.ForeignKey(
        Intervention, on_delete=models.CASCADE, related_name="recipients"
    )
    farmer = models.ForeignKey(
        Farmer, on_delete=models.PROTECT, related_name="intervention_recipients"
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="PENDING")
    quantity_received = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    received_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["farmer__last_name", "farmer__first_name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["intervention", "farmer"], name="unique_intervention_recipient"
            )
        ]

    def __str__(self):
        return f"{self.intervention.reference_id} - {self.farmer.list_name}"


@receiver(post_save, sender=Intervention)
def ensure_individual_recipient(sender, instance, **kwargs):
    """Keep legacy and programmatic one-farmer records reportable as recipient snapshots."""
    if instance.farmer_id:
        InterventionRecipient.objects.get_or_create(
            intervention=instance,
            farmer_id=instance.farmer_id,
            defaults={
                "status": "RECEIVED" if instance.status == "COMPLETED" else "PENDING",
                "received_at": (
                    instance.intervention_date if instance.status == "COMPLETED" else None
                ),
            },
        )
