from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.farmers.models import Farmer
from apps.service_requests.models import ServiceRequest


class Intervention(models.Model):
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

    farmer = models.ForeignKey(Farmer, on_delete=models.PROTECT, related_name="interventions")
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
        return f"{self.reference_id} - {self.farmer.list_name}"
