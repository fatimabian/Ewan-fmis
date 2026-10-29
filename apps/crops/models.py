from django.conf import settings
from django.db import models

from apps.farm_parcels.models import FarmParcel


class CropRecord(models.Model):
    parcel = models.ForeignKey(FarmParcel, on_delete=models.CASCADE, related_name="crops")
    crop_type = models.CharField(max_length=100)
    variety = models.CharField(
        max_length=120,
        blank=True,
        help_text="Specific variety or breed, for example Saba, Latundan, Native Chicken, or Broiler.",
    )
    cropping_schedule = models.CharField(
        max_length=40,
        blank=True,
        help_text="Recorded production schedule, for example Jan-Mar",
    )
    area_hectares = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    number_of_heads = models.PositiveIntegerField(null=True, blank=True)
    is_organic = models.BooleanField(default=False)
    is_intercrop = models.BooleanField(default=False)
    planting_date = models.DateField(null=True, blank=True)
    harvest_date = models.DateField(null=True, blank=True)
    image = models.ImageField(upload_to="crop_photos/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="archived_crop_records",
    )

    def __str__(self):
        return self.crop_type

    @property
    def symbol(self):
        from apps.common.crop_symbols import crop_symbol

        return crop_symbol(self.crop_type)
