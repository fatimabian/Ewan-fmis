from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.common.constants import (
    ROSARIO_BARANGAY_CHOICES,
    ROSARIO_CROP_CHOICES,
    ROSARIO_MUNICIPALITY,
    ROSARIO_PROVINCE,
)
from apps.common.forms import (
    InlineValidationMixin,
    RequiredYesNoField,
    add_other_crop_field,
    resolve_other_crop,
)
from apps.crops.models import CropRecord
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.farmers.models import FarmerUpdateHistory

from .models import FarmParcel


class FarmParcelForm(InlineValidationMixin, forms.ModelForm):
    farmer = FarmerChoiceField(queryset=active_farmer_queryset())
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES)
    farm_type = forms.CharField(
        max_length=30,
        required=True,
        label="Farm type",
        widget=forms.Select(choices=FarmParcel.FARM_TYPE_CHOICES),
    )
    is_rsbsa_recorded = RequiredYesNoField(label="Already recorded in RSBSA?")
    is_active = RequiredYesNoField(label="Currently cultivated / active?")
    transaction_code = forms.CharField(
        max_length=80,
        required=False,
        label="Slip B transaction code",
    )
    change_reason = forms.ChoiceField(
        choices=FarmerUpdateHistory.CHANGE_REASON_CHOICES,
        required=False,
        label="Reason for change",
    )
    update_remarks = forms.CharField(
        required=False,
        label="Updating slip remarks",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    date_signed = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_received = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    agriculturist_name = forms.CharField(max_length=180, required=False)
    registrant_declaration = forms.BooleanField(
        required=False,
        label="The registrant confirms the Slip B information and privacy declaration.",
    )

    class Meta:
        model = FarmParcel
        fields = [
            "farmer",
            "barangay",
            "municipality",
            "province",
            "area_hectares",
            "ownership_type",
            "land_type",
            "farm_type",
            "ownership_document",
            "ownership_document_other",
            "land_owner_name",
            "land_owner_registered_rsbsa",
            "land_owner_rsbsa_number",
            "within_ancestral_domain",
            "agrarian_reform_beneficiary",
            "is_rsbsa_recorded",
            "coordinates",
            "georef_id",
            "gpx_status",
            "rotational_tiller",
            "remarks",
            "is_active",
            "transaction_code",
            "change_reason",
            "update_remarks",
            "date_signed",
            "date_received",
            "agriculturist_name",
            "registrant_declaration",
        ]
        labels = {
            "farmer": "Existing Farmer ID / RSBSA Number",
            "area_hectares": "Total farm area (ha)",
            "ownership_type": "Ownership / tenure status",
            "ownership_document": "Proof of ownership / tenure",
            "ownership_document_other": "Other ownership document (specify)",
            "land_owner_registered_rsbsa": "Land owner is registered in RSBSA",
            "within_ancestral_domain": "Within ancestral domain",
            "agrarian_reform_beneficiary": "Agrarian Reform Beneficiary (ARB)",
            "is_rsbsa_recorded": "Parcel already recorded in RSBSA",
            "coordinates": "GPS coordinates",
            "georef_id": "Georeference / GPX ID",
            "gpx_status": "GPX / georeference status",
            "rotational_tiller": "Uses a rotational tiller",
            "remarks": "Parcel remarks",
            "is_active": "Currently cultivated / active",
        }
        widgets = {"area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area_hectares"].min_value = 0.01
        self.fields["gpx_status"].required = False
        for name, fixed_value in (
            ("municipality", ROSARIO_MUNICIPALITY),
            ("province", ROSARIO_PROVINCE),
        ):
            self.fields[name].initial = fixed_value
            self.initial[name] = fixed_value
            self.fields[name].disabled = True
        self.fields["farmer"].queryset = active_farmer_queryset(
            self.instance.farmer_id if self.instance and self.instance.pk else None
        )
        if self.instance and self.instance.pk:
            self.fields["farmer"].disabled = True
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("ownership_document") == "OTHER" and not cleaned.get(
            "ownership_document_other"
        ):
            self.add_error(
                "ownership_document_other",
                "Specify the other ownership or tenure document.",
            )
        if cleaned.get("land_owner_registered_rsbsa") is True and not cleaned.get(
            "land_owner_rsbsa_number"
        ):
            self.add_error(
                "land_owner_rsbsa_number",
                "Enter the land owner's RSBSA number.",
            )
        if cleaned.get("gpx_status") == "KNOWN" and not cleaned.get("georef_id"):
            self.add_error("georef_id", "Enter the GPX / Georeference ID.")
        return cleaned


class ParcelCropForm(InlineValidationMixin, forms.ModelForm):
    crop_type = forms.ChoiceField(
        choices=ROSARIO_CROP_CHOICES,
        label="Crop / Commodity",
    )
    is_organic = RequiredYesNoField(label="Organic production?")
    is_intercrop = RequiredYesNoField(label="Intercropping commodity?")

    class Meta:
        model = CropRecord
        fields = [
            "crop_type",
            "cropping_schedule",
            "area_hectares",
            "number_of_heads",
            "is_organic",
            "is_intercrop",
            "planting_date",
            "harvest_date",
            "image",
        ]
        labels = {
            "crop_type": "Crop / Commodity",
            "cropping_schedule": "Cropping schedule (for example, Jan-Mar)",
            "area_hectares": "Size / Area Planted (ha)",
            "number_of_heads": "Number of heads / trees (if applicable)",
            "is_organic": "Organic production",
            "is_intercrop": "Intercropping commodity",
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
        add_other_crop_field(self)
        self.order_fields(
            ["crop_type", "other_crop_name"]
            + [name for name in self.fields if name not in {"crop_type", "other_crop_name"}]
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
        planting_date = cleaned.get("planting_date")
        harvest_date = cleaned.get("harvest_date")
        if planting_date and harvest_date and harvest_date < planting_date:
            self.add_error("harvest_date", "Harvest date cannot be earlier than planting date.")
        return cleaned


class RequiredParcelCropFormSet(BaseInlineFormSet):
    """Require one crop and validate every additional crop row the user adds."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.empty_permitted = False

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        parcel_area = self.instance.area_hectares
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            crop_area = form.cleaned_data.get("area_hectares")
            if parcel_area and crop_area and crop_area > parcel_area:
                form.add_error(
                    "area_hectares",
                    f"Area planted cannot exceed the parcel area of {parcel_area} ha.",
                )


ParcelCropFormSet = inlineformset_factory(
    FarmParcel,
    CropRecord,
    form=ParcelCropForm,
    formset=RequiredParcelCropFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
