from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import models

from apps.farmers.models import Farmer


def parcel_photo_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"parcel_photos/parcel_{instance.parcel_id}/{uuid4().hex}{extension}"


class FarmParcel(models.Model):
    OWNERSHIP_CHOICES = [
        ("OWNED", "Registered Owner"),
        ("TENANT", "Tenant"),
        ("LEASED", "Lessee"),
        ("ARB", "Agrarian Reform Beneficiary"),
        ("OTHER", "Other"),
    ]
    # AFTER
    LAND_TYPE_CHOICES = [
        ("UPLAND", "Upland"),
        ("LOWLAND", "Lowland"),
    ]
    FARM_TYPE_CHOICES = [
        ("Irrigated", "Irrigated"),
        ("Rainfed Upland", "Rainfed Upland"),
        ("Rainfed Lowland", "Rainfed Lowland"),
    ]
    GPX_STATUS_CHOICES = [
        ("KNOWN", "GPX / Georeference ID recorded"),
        ("FORGOT", "Farmer forgot the GPX / Georeference ID"),
        ("NOT_GEOREFERENCED", "Not yet georeferenced"),
    ]
    OWNERSHIP_DOCUMENT_CHOICES = [
        ("Certificate of Land Transfer", "Certificate of Land Transfer"),
        ("Emancipation Patent", "Emancipation Patent"),
        (
            "Individual CLOA",
            "Individual Certificate of Land Ownership Award (CLOA)",
        ),
        ("Collective CLOA", "Collective CLOA"),
        ("Co-Ownership CLOA", "Co-Ownership CLOA"),
        ("Agricultural Sales Patent", "Agricultural Sales Patent"),
        ("Homestead Patent", "Homestead Patent"),
        ("Free Patent", "Free Patent"),
        ("Certificate of Title", "Certificate of Title / Regular Title"),
        ("Ancestral Domain Title", "Certificate of Ancestral Domain Title"),
        ("Ancestral Land Title", "Certificate of Ancestral Land Title"),
        ("Tax Declaration", "Tax Declaration"),
        ("OTHER", "Other (for example, Barangay Certification)"),
    ]

    farmer = models.ForeignKey(Farmer, on_delete=models.CASCADE, related_name="parcels")
    parcel_name = models.CharField(max_length=120, blank=True)
    barangay = models.CharField(max_length=100)
    municipality = models.CharField(max_length=100, default="Rosario")
    province = models.CharField(max_length=100, default="Batangas")
    area_hectares = models.DecimalField(max_digits=10, decimal_places=2)
    ownership_type = models.CharField(max_length=30, choices=OWNERSHIP_CHOICES)
    land_type = models.CharField(max_length=30, choices=LAND_TYPE_CHOICES, default="")
    farm_type = models.CharField(
        max_length=180,
        blank=True,
        default="",
    )
    within_ancestral_domain = models.BooleanField(null=True, blank=True)
    agrarian_reform_beneficiary = models.BooleanField(null=True, blank=True)
    ownership_document = models.CharField(
        max_length=80,
        choices=OWNERSHIP_DOCUMENT_CHOICES,
        blank=True,
    )
    ownership_document_other = models.CharField(max_length=180, blank=True)
    land_owner_name = models.CharField(max_length=180, blank=True)
    land_owner_registered_rsbsa = models.BooleanField(null=True, blank=True)
    land_owner_rsbsa_number = models.CharField(max_length=40, blank=True)
    is_rsbsa_recorded = models.BooleanField(default=False)
    georef_id = models.CharField(max_length=80, blank=True)
    gpx_status = models.CharField(
        max_length=20,
        choices=GPX_STATUS_CHOICES,
        default="KNOWN",
    )
    rotational_tiller = models.BooleanField(null=True, blank=True)
    remarks = models.TextField(blank=True, max_length=1000)
    is_active = models.BooleanField(default=True)
    coordinates = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_name(self):
        return self.parcel_name or f"Parcel {self.pk:03d}"

    def __str__(self):
        return f"{self.display_name} - {self.farmer}"

    def get_farm_type_display(self):
        """Keep existing reports/templates compatible now that farm type is staff-entered."""
        return self.farm_type


class FarmParcelPhoto(models.Model):
    parcel = models.ForeignKey(FarmParcel, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to=parcel_photo_upload_path)
    caption = models.CharField(max_length=180, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_parcel_photos",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_parcel_photos",
    )

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.parcel.display_name} field photo"
