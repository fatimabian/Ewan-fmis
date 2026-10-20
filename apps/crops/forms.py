from django import forms
from django.db.models import Sum

from apps.farm_parcels.models import FarmParcel
from apps.common.constants import LIVESTOCK_COMMODITIES, MONTH_CHOICES, ROSARIO_CROP_CHOICES
from apps.common.forms import (
    InlineValidationMixin,
    RequiredYesNoField,
    add_other_crop_field,
    resolve_other_crop,
)

from .models import CropRecord


class ParcelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, parcel):
        return (
            f"{parcel.farmer.record_id} - {parcel.farmer.list_name} / "
            f"{parcel.display_name} ({parcel.barangay})"
        )

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
        label="Commodity",
    )
    is_organic = RequiredYesNoField(label="Organic production?")
    is_intercrop = RequiredYesNoField(label="Intercropping commodity?")
    cropping_start_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        label="Cropping schedule start",
    )
    cropping_end_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        label="Cropping schedule end",
    )

    class Meta:
        model = CropRecord
        fields = [
            "parcel",
            "crop_type",
            "area_hectares",
            "number_of_heads",
            "is_organic",
            "is_intercrop",
        ]
        labels = {
            "parcel": "Existing Farmer ID and Farm Parcel",
            "crop_type": "Commodity",
            "area_hectares": "Size / Area Planted (ha)",
            "number_of_heads": "Number of heads / trees (if applicable)",
            "is_organic": "Organic production",
            "is_intercrop": "Intercropping commodity",
        }
        widgets = {
            "crop_type": forms.TextInput(attrs={"placeholder": "e.g., Rice, Corn, Banana"}),
            "area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "number_of_heads": forms.NumberInput(attrs={"min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_other_crop_field(self)
        schedule = self.initial.get("cropping_schedule") or getattr(
            self.instance, "cropping_schedule", ""
        )
        if schedule:
            parts = [part.strip() for part in schedule.replace("–", "-").split("-", 1)]
            if len(parts) == 2:
                month_names = {value for value, _label in MONTH_CHOICES if value}
                month_lookup = {name[:3].lower(): name for name in month_names}
                start_month = month_lookup.get(parts[0][:3].lower(), parts[0])
                end_month = month_lookup.get(parts[1][:3].lower(), parts[1])
                if start_month in month_names and end_month in month_names:
                    self.initial.setdefault("cropping_start_month", start_month)
                    self.initial.setdefault("cropping_end_month", end_month)
        self.order_fields(
            [
                "parcel",
                "crop_type",
                "other_crop_name",
                "cropping_start_month",
                "cropping_end_month",
            ]
            + [
                name
                for name in self.fields
                if name
                not in {
                    "parcel",
                    "crop_type",
                    "other_crop_name",
                    "cropping_start_month",
                    "cropping_end_month",
                }
            ]
        )
        existing_crop = self.instance.crop_type if self.instance and self.instance.pk else ""
        available_crops = {value for value, _label in self.fields["crop_type"].choices}
        if existing_crop and existing_crop not in available_crops:
            self.fields["crop_type"].choices = tuple(self.fields["crop_type"].choices) + (
                (existing_crop, existing_crop),
            )
        self.fields["area_hectares"].min_value = 0.01
        self.fields["area_hectares"].required = False
        self.fields["crop_type"].widget.attrs["data-commodity-type"] = "true"
        self.fields["crop_type"].widget.attrs["data-livestock-values"] = "|".join(
            sorted(LIVESTOCK_COMMODITIES)
        )
        self.fields["area_hectares"].widget.attrs["data-commodity-area"] = "true"
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        resolve_other_crop(self, cleaned)
        parcel = cleaned.get("parcel")
        area = cleaned.get("area_hectares")
        commodity = cleaned.get("crop_type")
        start_month = cleaned.get("cropping_start_month")
        end_month = cleaned.get("cropping_end_month")
        cleaned["cropping_schedule"] = (
            f"{start_month} - {end_month}" if start_month and end_month else ""
        )
        if commodity in LIVESTOCK_COMMODITIES:
            cleaned["area_hectares"] = None
            area = None
        elif not area:
            self.add_error("area_hectares", "Enter the area used for this commodity.")
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

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.cropping_schedule = self.cleaned_data.get("cropping_schedule", "")
        if commit:
            instance.save()
            self.save_m2m()
        return instance
