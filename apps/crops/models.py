from django.db import models

from apps.farm_parcels.models import FarmParcel


class CropRecord(models.Model):
    parcel = models.ForeignKey(FarmParcel, on_delete=models.CASCADE, related_name="crops")
    crop_type = models.CharField(max_length=100)
    cropping_schedule = models.CharField(max_length=100, blank=True)
    area_hectares = models.DecimalField(max_digits=10, decimal_places=2)
    number_of_heads = models.PositiveIntegerField(null=True, blank=True)
    is_organic = models.BooleanField(default=False)
    planting_date = models.DateField(null=True, blank=True)
    harvest_date = models.DateField(null=True, blank=True)
    image = models.ImageField(upload_to="crop_photos/", blank=True)

    def __str__(self):
        return self.crop_type
