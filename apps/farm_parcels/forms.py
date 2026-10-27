from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone

from apps.common.constants import (
    FISHERY_COMMODITIES,
    LIVESTOCK_COMMODITIES,
    MONTH_CHOICES,
    ROSARIO_BARANGAY_CHOICES,
    ROSARIO_CROP_CHOICES,
    ROSARIO_COMMODITY_VALUES,
    ROSARIO_MUNICIPALITY,
    ROSARIO_PROVINCE,
)
from apps.common.forms import (
    InlineValidationMixin,
    MultipleImageField,
    RequiredYesNoField,
    YesNoNAField,
    add_other_crop_field,
    normalize_person_name,
    resolve_other_crop,
)
from apps.crops.models import CropRecord
from apps.farmers.form_fields import FarmerChoiceField, active_farmer_queryset
from apps.farmers.models import FarmerUpdateHistory

from .models import FarmParcel


class FarmParcelPhotoUploadForm(InlineValidationMixin, forms.Form):
    """Office-only field evidence uploaded outside the Slip B workflow."""

    field_photo = MultipleImageField(
        required=True,
        label="Upload field photo",
        help_text="Select one current photo of the field.",
        widget=forms.ClearableFileInput(
            attrs={"accept": "image/png,image/jpeg,image/webp"}
        ),
    )


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
    within_ancestral_domain = YesNoNAField(
        required=False,
        label="Within ancestral domain",
        choices=(("", "Select Yes or No"), ("True", "Yes"), ("False", "No")),
    )
    agrarian_reform_beneficiary = YesNoNAField(
        required=False,
        label="Agrarian Reform Beneficiary (ARB)",
        choices=(("", "Select Yes or No"), ("True", "Yes"), ("False", "No")),
    )
    rotational_tiller = YesNoNAField(
        required=False,
        label="Uses a rotational tiller",
        choices=(("", "Select Yes or No"), ("True", "Yes"), ("False", "No")),
    )
    transaction_code = forms.CharField(
        max_length=80,
        required=False,
        label="Update record transaction code",
    )
    change_reason = forms.ChoiceField(
        choices=FarmerUpdateHistory.CHANGE_REASON_CHOICES,
        required=False,
        label="Reason for change",
    )
    update_remarks = forms.CharField(
        required=False,
        label="Update record remarks",
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
        label="The registrant confirms the updated information and privacy declaration.",
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
            "rotational_tiller": "Uses a rotational tiller",
            "remarks": "Parcel remarks",
            "is_active": "Currently cultivated / active",
        }
        widgets = {"area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["area_hectares"].min_value = 0.01
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
        for name in ("land_owner_name", "agriculturist_name"):
            if cleaned.get(name):
                try:
                    cleaned[name] = normalize_person_name(cleaned[name])
                except forms.ValidationError as error:
                    self.add_error(name, error)
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
        return cleaned


class ParcelCropForm(InlineValidationMixin, forms.ModelForm):
    crop_type = forms.ChoiceField(choices=ROSARIO_CROP_CHOICES, label="Commodity")
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
            "crop_type",
            "area_hectares",
            "number_of_heads",
            "is_organic",
            "is_intercrop",
        ]
        labels = {
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
                    "crop_type",
                    "other_crop_name",
                    "cropping_start_month",
                    "cropping_end_month",
                }
            ]
        )
        existing_crop = self.instance.crop_type if self.instance and self.instance.pk else ""
        available_crops = ROSARIO_COMMODITY_VALUES
        if existing_crop and existing_crop not in available_crops:
            self.fields["crop_type"].choices = tuple(self.fields["crop_type"].choices) + (
                (existing_crop, existing_crop),
            )
        self.fields["area_hectares"].min_value = 0.01
        self.fields["area_hectares"].required = False
        self.fields["cropping_start_month"].required = False
        self.fields["cropping_end_month"].required = False
        self.fields["is_intercrop"].required = False
        self.fields["crop_type"].widget.attrs["data-commodity-type"] = "true"
        self.fields["crop_type"].widget.attrs["data-livestock-values"] = "|".join(
            sorted(LIVESTOCK_COMMODITIES)
        )
        self.fields["crop_type"].widget.attrs["data-fishery-values"] = "|".join(
            sorted(FISHERY_COMMODITIES)
        )
        self.fields["area_hectares"].widget.attrs["data-commodity-area"] = "true"
        for field in self.fields.values():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        resolve_other_crop(self, cleaned)
        commodity = cleaned.get("crop_type")
        start_month = cleaned.get("cropping_start_month")
        end_month = cleaned.get("cropping_end_month")
        if commodity in LIVESTOCK_COMMODITIES:
            cleaned["area_hectares"] = None
            cleaned["is_intercrop"] = False
            if not cleaned.get("number_of_heads"):
                self.add_error("number_of_heads", "Enter the number of animal heads.")
        elif commodity in FISHERY_COMMODITIES:
            cleaned["is_intercrop"] = False
        elif not cleaned.get("area_hectares"):
            self.add_error("area_hectares", "Enter the area used for this commodity.")
        elif not start_month or not end_month:
            if not start_month:
                self.add_error("cropping_start_month", "Select the first cropping month.")
            if not end_month:
                self.add_error("cropping_end_month", "Select the last cropping month.")
        if commodity not in LIVESTOCK_COMMODITIES | FISHERY_COMMODITIES and cleaned.get("is_intercrop") is None:
            self.add_error("is_intercrop", "Select whether this is an intercropping commodity.")
        cleaned["cropping_schedule"] = (
            f"{start_month} - {end_month}"
            if commodity not in FISHERY_COMMODITIES and start_month and end_month
            else ""
        )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.cropping_schedule = self.cleaned_data.get("cropping_schedule", "")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class RequiredParcelCropFormSet(BaseInlineFormSet):
    """Require one crop and validate every additional crop row the user adds."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.empty_permitted = False

    def delete_existing(self, obj, commit=True):
        """Archive removed crop rows instead of erasing operational history."""
        obj.is_active = False
        obj.archived_at = timezone.now()
        obj.archived_by = getattr(self, "archive_actor", None)
        if commit:
            obj.save(update_fields=["is_active", "archived_at", "archived_by"])

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        parcel_area = self.instance.area_hectares
        primary_crop_area = 0
        primary_crop_forms = []
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            crop_area = form.cleaned_data.get("area_hectares")
            if parcel_area and crop_area and crop_area > parcel_area:
                form.add_error(
                    "area_hectares",
                    f"Area planted cannot exceed the parcel area of {parcel_area} ha.",
                )
            if crop_area and form.cleaned_data.get("is_intercrop") is False:
                primary_crop_area += crop_area
                primary_crop_forms.append(form)
        if parcel_area and primary_crop_area > parcel_area:
            message = (
                f"Active non-intercrop crops total {primary_crop_area} ha, "
                f"which exceeds the parcel area of {parcel_area} ha."
            )
            for form in primary_crop_forms:
                form.add_error("area_hectares", message)


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
