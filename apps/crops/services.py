from django.db.models import Sum
from .models import CropRecord


def crop_areas():
    return CropRecord.objects.values("crop_type").annotate(area=Sum("area_hectares")).order_by("-area")
