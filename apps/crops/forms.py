from django import forms
from django.db.models import Sum

from apps.farm_parcels.models import FarmParcel
from apps.common.constants import ROSARIO_CROP_CHOICES
from apps.common.forms import (
    InlineValidationMixin,
    RequiredYesNoField,
    add_other_crop_field,
    resolve_other_crop,
)

from .models import CropRecord


class ParcelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, parcel):
        return f"{parcel.farmer.record_id} - {parcel.farmer.list_name} / Parcel {parcel.pk:03d} ({parcel.barangay})"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.widget.attrs.update(
            {
                "data-farmer-picker": "true",
                "data-search-placeholder": "Search Farmer ID, farmer name, barangay, or parcel...",
            }
        )


class CropRecordForm(InlineValidationMixin, forms.ModelForm):
    parcel = ParcelChoiceField(
        queryset=FarmParcel.objects.select_related("farmer").filter(is_active=True)
    )
    crop_type = forms.ChoiceField(
        choices=ROSARIO_CROP_CHOICES,
        label="Crop / Commodity",
    )
    is_organic = RequiredYesNoField(label="Organic production?")
    is_intercrop = RequiredYesNoField(label="Intercropping commodity?")

    class Meta:
        model = CropRecord
        fields = [
            "parcel",
            "crop_type",
            "cropping_schedule",
            "area_hectares",
            "number_of_heads",
            "is_organic",
            "is_intercrop",
            "planting_date",
            "image",
        ]
        labels = {
            "parcel": "Existing Farmer ID and Farm Parcel",
            "crop_type": "Crop / Commodity",
            "cropping_schedule": "Cropping schedule (for example, Jan-Mar)",
            "area_hectares": "Size / Area Planted (ha)",
            "number_of_heads": "Number of heads / trees (if applicable)",
            "is_organic": "Organic production",
            "is_intercrop": "Intercropping commodity",
            "image": "Crop photo (optional)",
        }
        widgets = {
            "crop_type": forms.TextInput(attrs={"placeholder": "e.g., Rice, Corn, Banana"}),
            "area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "number_of_heads": forms.NumberInput(attrs={"min": "0"}),
            "planting_date": forms.DateInput(attrs={"type": "date"}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_other_crop_field(self)
        self.order_fields(
            ["parcel", "crop_type", "other_crop_name"]
            + [
                name
                for name in self.fields
                if name not in {"parcel", "crop_type", "other_crop_name"}
            ]
        )
        existing_crop = self.instance.crop_type if self.instance and self.instance.pk else ""
        available_crops = {value for value, _label in self.fields["crop_type"].choices}
        if existing_crop and existing_crop not in available_crops:
            self.fields["crop_type"].choices = tuple(self.fields["crop_type"].choices) + (
                (existing_crop, existing_crop),
            )
        self.fields["area_hectares"].min_value = 0.01
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        resolve_other_crop(self, cleaned)
        parcel = cleaned.get("parcel")
        area = cleaned.get("area_hectares")
        if parcel and area and area > parcel.area_hectares:
            self.add_error(
                "area_hectares",
                f"Area planted cannot exceed the parcel area of {parcel.area_hectares} ha.",
            )
        if parcel and area and cleaned.get("is_intercrop") is False:
            existing = CropRecord.objects.filter(
                parcel=parcel,
                is_active=True,
                is_intercrop=False,
            )
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            recorded_area = existing.aggregate(total=Sum("area_hectares"))["total"] or 0
            if recorded_area + area > parcel.area_hectares:
                self.add_error(
                    "area_hectares",
                    (
                        f"Active non-intercrop crops would total {recorded_area + area} ha, "
                        f"which exceeds this parcel's {parcel.area_hectares} ha."
                    ),
                )
        return cleaned
