from django.db.models import Sum
from .models import CropRecord


def crop_areas():
    return (
        CropRecord.objects.filter(
            is_active=True,
            parcel__is_active=True,
            parcel__farmer__is_active=True,
        ).values("crop_type").annotate(area=Sum("area_hectares")).order_by("-area")
    )
