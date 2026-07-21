from django.db.models import Sum
from .models import FarmParcel
def total_area(): return FarmParcel.objects.aggregate(total=Sum("area_hectares"))["total"] or 0
