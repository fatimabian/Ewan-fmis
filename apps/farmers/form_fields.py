from django import forms
from django.db.models import Q

from .models import Farmer


class FarmerChoiceField(forms.ModelChoiceField):
    """One consistent farmer label for every operational module."""

    def label_from_instance(self, farmer):
        rsbsa = f" / RSBSA {farmer.rsbsa_number}" if farmer.rsbsa_number else ""
        return f"{farmer.record_id}{rsbsa} - {farmer.list_name} ({farmer.barangay})"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget.attrs.update({
            "data-farmer-picker": "true",
            "data-search-placeholder": "Search Farmer ID, RSBSA number, name, or barangay...",
        })


def active_farmer_queryset(include_pk=None):
    filters = Q(is_active=True)
    if include_pk:
        filters |= Q(pk=include_pk)
    return Farmer.objects.filter(filters).order_by("last_name", "first_name", "pk")
