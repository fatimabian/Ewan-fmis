from django import forms

from apps.farm_parcels.models import FarmParcel
from apps.common.forms import InlineValidationMixin

from .models import CropRecord


class ParcelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, parcel):
        return f"{parcel.farmer.record_id} - {parcel.farmer.list_name} / Parcel {parcel.pk:03d} ({parcel.barangay})"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget.attrs.update({
            "data-farmer-picker": "true",
            "data-search-placeholder": "Search Farmer ID, farmer name, barangay, or parcel...",
        })


class CropRecordForm(InlineValidationMixin, forms.ModelForm):
    parcel = ParcelChoiceField(queryset=FarmParcel.objects.select_related("farmer").filter(is_active=True))

    class Meta:
        model = CropRecord
        fields = [
            "parcel", "crop_type", "area_hectares", "number_of_heads",
            "is_organic", "planting_date", "harvest_date", "image",
]
        labels = {
            "parcel": "Existing Farmer ID and Farm Parcel",
            "crop_type": "Crop / Commodity",
            "area_hectares": "Size / Area Planted (ha)",
            "number_of_heads": "Number of heads / trees (if applicable)",
            "is_organic": "Organic production",
            "harvest_date": "Expected or actual harvest date",
            "image": "Crop photo (optional)",
        }
        widgets = {
            "crop_type": forms.TextInput(attrs={"placeholder": "e.g., Rice, Corn, Banana"}),
            "area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "number_of_heads": forms.NumberInput(attrs={"min": "0"}),
            "planting_date": forms.DateInput(attrs={"type": "date"}),
            "harvest_date": forms.DateInput(attrs={"type": "date"}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area_hectares"].min_value = 0.01
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        parcel = cleaned.get("parcel")
        area = cleaned.get("area_hectares")
        planting_date = cleaned.get("planting_date")
        harvest_date = cleaned.get("harvest_date")
        if parcel and area and area > parcel.area_hectares:
            self.add_error("area_hectares", f"Area planted cannot exceed the parcel area of {parcel.area_hectares} ha.")
        if planting_date and harvest_date and harvest_date < planting_date:
            self.add_error("harvest_date", "Harvest date cannot be earlier than the planting date.")
        return cleaned
