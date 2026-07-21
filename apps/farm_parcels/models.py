from django.db import models

from apps.farmers.models import Farmer


class FarmParcel(models.Model):
    OWNERSHIP_CHOICES = [
        ("OWNED", "Registered Owner"),
        ("TENANT", "Tenant"),
        ("LEASED", "Lessee"),
        ("ARB", "Agrarian Reform Beneficiary"),
        ("OTHER", "Other"),
    ]
    LAND_TYPE_CHOICES = [
        ("FLATLAND", "Flatland"),
        ("UPLAND", "Upland"),
        ("LOWLAND", "Lowland"),
    ]
    FARM_TYPE_CHOICES = [
        ("IRRIGATED", "Irrigated"),
        ("RAINFED_UPLAND", "Rainfed Upland"),
        ("RAINFED_LOWLAND", "Rainfed Lowland"),
        ("NOT_APPLICABLE", "Not Applicable"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="parcels")
    parcel_name = models.CharField(max_length=120, blank=True)
    barangay = models.CharField(max_length=100)
    municipality = models.CharField(max_length=100, default="Rosario")
    province = models.CharField(max_length=100, default="Batangas")
    area_hectares = models.DecimalField(max_digits=10, decimal_places=2)
    ownership_type = models.CharField(max_length=30, choices=OWNERSHIP_CHOICES)
    land_type = models.CharField(max_length=30, choices=LAND_TYPE_CHOICES, default="FLATLAND")
    farm_type = models.CharField(max_length=30, choices=FARM_TYPE_CHOICES, default="IRRIGATED")
    within_ancestral_domain = models.BooleanField(null=True, blank=True)
    agrarian_reform_beneficiary = models.BooleanField(null=True, blank=True)
    ownership_document = models.CharField(max_length=180, blank=True)
    land_owner_name = models.CharField(max_length=180, blank=True)
    land_owner_registered_rsbsa = models.BooleanField(null=True, blank=True)
    is_rsbsa_recorded = models.BooleanField(default=False)
    is_organic = models.BooleanField(default=False)
    georef_id = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    coordinates = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_name(self):
        return self.parcel_name or f"Parcel {self.pk:03d}"

    def __str__(self):
        return f"{self.display_name} - {self.farmer}"
