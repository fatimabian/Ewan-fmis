from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory

from apps.crops.models import CropRecord
from apps.common.constants import (
    ROSARIO_BARANGAY_CHOICES,
    ROSARIO_CROP_CHOICES,
    ROSARIO_MUNICIPALITY,
    ROSARIO_PROVINCE,
    ROSARIO_REGION,
)
from apps.common.forms import (
    InlineValidationMixin,
    RequiredYesNoField,
    add_other_crop_field,
    resolve_other_crop,
)
from apps.farm_parcels.models import FarmParcel

from .models import Farmer, FarmerDocument, FarmerUpdateHistory

ACTIVITY_CHOICES = [
    ("FARMER_CROPS", "Farmer - Crops"),
    ("FARMER_LIVESTOCK", "Farmer - Livestock"),
    ("FARMER_POULTRY", "Farmer - Poultry"),
    ("WORK_LAND_PREPARATION", "Farm Worker - Land Preparation"),
    ("WORK_PLANTING", "Farm Worker - Planting / Transplanting"),
    ("WORK_CULTIVATION", "Farm Worker - Cultivation"),
    ("WORK_HARVESTING", "Farm Worker - Harvesting"),
    ("FISH_CAPTURE", "Fisherfolk - Fish Capture"),
    ("FISH_AQUACULTURE", "Fisherfolk - Aquaculture"),
    ("FISH_GLEANING", "Fisherfolk - Gleaning"),
    ("FISH_PROCESSING", "Fisherfolk - Processing"),
    ("FISH_VENDING", "Fisherfolk - Vending"),
    ("YOUTH_HOUSEHOLD", "Agri-Youth - Farming Household Member"),
    ("YOUTH_FORMAL", "Agri-Youth - Formal Agriculture Course"),
    ("YOUTH_NONFORMAL", "Agri-Youth - Non-formal Agriculture Course"),
    ("YOUTH_PROGRAM", "Agri-Youth - Agriculture Activity / Program"),
]


class StyledFormMixin(InlineValidationMixin):
    def apply_styles(self):
        for field in self.fields.values():
            if isinstance(
                field.widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)
            ):
                continue
            field.widget.attrs.setdefault("class", "form-control")


class FarmerRegistrationForm(StyledFormMixin, forms.ModelForm):
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES, required=True)
    activities = forms.ChoiceField(
        choices=(("", "Select farmer type or primary activity"),) + tuple(ACTIVITY_CHOICES),
        widget=forms.Select,
        required=True,
        label="Farmer type / primary agricultural activity",
    )
    consent_given = forms.BooleanField(
        required=True,
        label="I confirm the information is correct and the farmer gave consent for RSBSA registration and data processing.",
    )

    class Meta:
        model = Farmer
        fields = [
            "last_name",
            "first_name",
            "middle_name",
            "extension_name",
            "sex",
            "birth_date",
            "place_of_birth",
            "mother_maiden_name",
            "house_lot_purok",
            "street_sitio",
            "barangay",
            "city_municipality",
            "province",
            "region",
            "phone_number",
            "email",
            "civil_status",
            "spouse_name",
            "highest_education",
            "valid_id_type",
            "valid_id_number",
            "philsys_registered",
            "philsys_pcn",
            "philsys_trn",
            "religion",
            "is_indigenous",
            "indigenous_group",
            "is_pwd",
            "is_four_ps",
            "fca_membership",
            "photo",
            "livelihood",
            "activities",
            "consent_given",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "sex": forms.Select,
            "civil_status": forms.Select,
            "livelihood": forms.Select,
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "phone_number": forms.TextInput(
                attrs={
                    "placeholder": "09XXXXXXXXX",
                    "maxlength": "11",
                    "inputmode": "numeric",
                    "pattern": "09[0-9]{9}",
                    "title": "Enter an 11-digit PH mobile number starting with 09",
                }
            ),
        }
        labels = {
            "extension_name": "Name extension (Jr., Sr., III)",
            "house_lot_purok": "House / Lot / Purok",
            "street_sitio": "Street / Sitio / Subdivision",
            "is_indigenous": "Member of an Indigenous People / ICC",
            "indigenous_group": "Indigenous group name",
            "is_pwd": "Person with Disability (PWD)",
            "is_four_ps": "4Ps beneficiary",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in (
            "sex",
            "birth_date",
            "place_of_birth",
            "mother_maiden_name",
            "barangay",
            "city_municipality",
            "province",
            "phone_number",
            "civil_status",
            "valid_id_type",
            "valid_id_number",
            "livelihood",
        ):
            if name in self.fields:
                self.fields[name].required = True
        for name, fixed_value in (
            ("city_municipality", ROSARIO_MUNICIPALITY),
            ("province", ROSARIO_PROVINCE),
            ("region", ROSARIO_REGION),
        ):
            if name in self.fields:
                self.fields[name].initial = fixed_value
                self.initial[name] = fixed_value
                self.fields[name].disabled = True
                self.fields[name].required = False
        civil_status = (
            self.data.get(self.add_prefix("civil_status"))
            if self.is_bound
            else self.initial.get("civil_status")
            or getattr(self.instance, "civil_status", "")
        )
        if "spouse_name" in self.fields:
            self.fields["spouse_name"].required = civil_status == "MARRIED"
            self.fields["spouse_name"].widget.attrs["data-required-for-married"] = "true"
        self.apply_styles()
        if "phone_number" in self.fields and not (self.instance and self.instance.pk):
            self.initial.setdefault("phone_number", "09")
        if (
            "activities" in self.fields
            and self.instance
            and self.instance.pk
            and self.instance.activities
        ):
            self.initial["activities"] = self.instance.activities.split(",")[0]

    def clean_phone_number(self):
        value = self.cleaned_data.get("phone_number", "")
        digits = "".join(ch for ch in value if ch.isdigit())
        if not digits:
            return digits
        if len(digits) != 11 or not digits.startswith("09"):
            raise ValidationError(
                "Enter a valid PH mobile number: 11 digits, starting with 09 (e.g. 09171234567)."
            )
        return digits

    def clean_activities(self):
        return self.cleaned_data["activities"]

    def clean(self):
        cleaned = super().clean()
        valid_id_type = cleaned.get("valid_id_type")
        valid_id_number = cleaned.get("valid_id_number")
        if valid_id_type and valid_id_number:
            duplicate = Farmer.objects.filter(
                valid_id_type__iexact=valid_id_type,
                valid_id_number__iexact=valid_id_number,
                is_active=True,
            )
            if self.instance and self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error(
                    "valid_id_number", "This ID is already linked to another active farmer record."
                )
        if cleaned.get("is_indigenous") and not cleaned.get("indigenous_group"):
            self.add_error("indigenous_group", "Enter the Indigenous People or ICC group name.")
        if (
            cleaned.get("civil_status") == "MARRIED"
            and not cleaned.get("spouse_name")
            and "spouse_name" not in self.errors
        ):
            self.add_error("spouse_name", "Enter the spouse's name for a married registrant.")
        if cleaned.get("philsys_registered") is True and not cleaned.get("philsys_pcn"):
            self.add_error("philsys_pcn", "Enter the PhilID / ePhilID PCN.")
        if cleaned.get("philsys_registered") is False and not cleaned.get("philsys_trn"):
            self.add_error("philsys_trn", "Enter the PhilSys transaction reference number (TRN).")
        return cleaned


class FarmerProfileUpdateForm(FarmerRegistrationForm):
    activities = None
    consent_given = forms.BooleanField(required=False, widget=forms.HiddenInput)
    transaction_code = forms.CharField(
        max_length=80,
        label="Transaction code",
        help_text="Official Slip A transaction code assigned by the encoder.",
    )
    change_reason = forms.ChoiceField(
        choices=FarmerUpdateHistory.CHANGE_REASON_CHOICES,
        label="Reason for change",
    )
    update_remarks = forms.CharField(
        required=False,
        label="Update remarks",
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
    agriculturist_name = forms.CharField(
        max_length=180,
        required=False,
        label="City / Municipal Agriculturist",
    )
    registrant_declaration = forms.BooleanField(
        required=True,
        label=(
            "The registrant confirms that the changes are true and consents to their use "
            "for RSBSA updating and legitimate agricultural services."
        ),
    )

    class Meta(FarmerRegistrationForm.Meta):
        fields = [
            field
            for field in FarmerRegistrationForm.Meta.fields
            if field not in {"livelihood", "activities"}
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()


class FarmerSlipBLivelihoodForm(StyledFormMixin, forms.ModelForm):
    activities = forms.ChoiceField(
        choices=(("", "Select farmer type or primary activity"),) + tuple(ACTIVITY_CHOICES),
        widget=forms.Select,
        required=True,
        label="Farmer type / primary agricultural activity",
    )
    transaction_code = forms.CharField(max_length=80, label="Transaction code")
    change_reason = forms.ChoiceField(
        choices=FarmerUpdateHistory.CHANGE_REASON_CHOICES,
        label="Reason for change",
    )
    update_remarks = forms.CharField(
        required=False,
        label="Slip B remarks",
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
        required=True,
        label="The registrant confirms the Slip B information and privacy declaration.",
    )

    class Meta:
        model = Farmer
        fields = ["livelihood", "activities"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.activities:
            self.initial["activities"] = self.instance.activities.split(",")[0]
        self.apply_styles()

    def clean_activities(self):
        return self.cleaned_data["activities"]


class ParcelRegistrationForm(StyledFormMixin, forms.ModelForm):
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES, required=True)
    is_rsbsa_recorded = RequiredYesNoField(label="Already recorded in RSBSA?")
    is_active = RequiredYesNoField(label="Currently cultivated / active?")
    farm_type = forms.ChoiceField(
        choices=FarmParcel.FARM_TYPE_CHOICES,
        required=True,
        label="Farm type",
    )

    class Meta:
        model = FarmParcel
        exclude = ["farmer", "created_at"]
        labels = {
            "is_rsbsa_recorded": "Already recorded in RSBSA",
            "within_ancestral_domain": "Within ancestral domain",
            "agrarian_reform_beneficiary": "Agrarian Reform Beneficiary (ARB)",
            "land_owner_registered_rsbsa": "Land owner is registered in RSBSA",
            "ownership_document": "Ownership / tenure document",
            "coordinates": "GPS coordinates",
            "georef_id": "Georeference / GPX ID",
        }
        widgets = {
            "area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("area_hectares", "ownership_type", "land_type"):
            self.fields[name].required = True
        for name, fixed_value in (
            ("municipality", ROSARIO_MUNICIPALITY),
            ("province", ROSARIO_PROVINCE),
        ):
            self.fields[name].initial = fixed_value
            self.initial[name] = fixed_value
            self.fields[name].disabled = True
        self.fields["gpx_status"].required = False
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        for name in ("barangay", "area_hectares", "ownership_type", "land_type", "farm_type"):
            if not cleaned.get(name):
                self.add_error(name, "Complete this field for the farm parcel.")
        return cleaned


class CropRegistrationForm(StyledFormMixin, forms.ModelForm):
    parcel_number = forms.IntegerField(
        min_value=1,
        required=False,
        label="Farm parcel",
        help_text="Select which farm parcel this crop belongs to.",
        widget=forms.Select(
            choices=(("", "Select farm parcel"),)
            + tuple((number, f"Farm Parcel {number}") for number in range(1, 51))
        ),
    )
    crop_type = forms.ChoiceField(
        choices=ROSARIO_CROP_CHOICES,
        required=False,
        label="Crop / Commodity",
    )
    is_organic = RequiredYesNoField(label="Organic production?")
    is_intercrop = RequiredYesNoField(label="Intercropping commodity?")

    class Meta:
        model = CropRecord
        exclude = ["parcel", "is_active", "archived_at", "archived_by"]
        labels = {
            "crop_type": "Crop / Commodity",
            "number_of_heads": "Number of heads / trees (if applicable)",
            "is_organic": "Organic production",
        }
        widgets = {
            "area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "planting_date": forms.DateInput(attrs={"type": "date"}),
            "harvest_date": forms.DateInput(attrs={"type": "date"}),
            "image": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_other_crop_field(self)
        self.order_fields(
            ["parcel_number", "crop_type", "other_crop_name"]
            + [
                name
                for name in self.fields
                if name not in {"parcel_number", "crop_type", "other_crop_name"}
            ]
        )
        for name in ("parcel_number", "crop_type", "area_hectares"):
            self.fields[name].required = False
            self.fields[name].widget.attrs["data-step-required"] = "true"
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        resolve_other_crop(self, cleaned)
        for name in ("parcel_number", "crop_type", "area_hectares"):
            if not cleaned.get(name):
                self.add_error(name, "Complete this field for the crop or commodity.")
        start, end = cleaned.get("planting_date"), cleaned.get("harvest_date")
        if start and end and end < start:
            self.add_error("harvest_date", "Harvest date cannot be earlier than the planting date.")
        return cleaned


class DocumentRegistrationForm(StyledFormMixin, forms.Form):
    document_type = forms.ChoiceField(choices=FarmerDocument.DOCUMENT_TYPE_CHOICES)
    description = forms.CharField(max_length=180, required=False)
    file = forms.FileField(help_text="JPG, PNG, or PDF; maximum 5 MB")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        self.fields["file"].widget.attrs["accept"] = ".jpg,.jpeg,.png,.pdf"

    def clean_file(self):
        upload = self.cleaned_data["file"]
        extension = Path(upload.name).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".pdf"}:
            raise ValidationError("Upload a JPG, PNG, or PDF file.")
        if upload.size > 5 * 1024 * 1024:
            raise ValidationError("Each document must be 5 MB or smaller.")
        position = upload.tell()
        header = upload.read(12)
        upload.seek(position)
        signatures = {
            ".pdf": header.startswith(b"%PDF-"),
            ".png": header.startswith(b"\x89PNG\r\n\x1a\n"),
            ".jpg": header.startswith(b"\xff\xd8\xff"),
            ".jpeg": header.startswith(b"\xff\xd8\xff"),
        }
        if not signatures.get(extension, False):
            raise ValidationError(
                "The file contents do not match the selected PDF or image format."
            )
        return upload


class BaseRequiredRegistrationFormSet(BaseFormSet):
    """Require the initial row and every row explicitly added by the user."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        form.empty_permitted = False


class BaseDocumentRegistrationFormSet(BaseRequiredRegistrationFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        document_types = {
            form.cleaned_data.get("document_type")
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        }
        if "VALID_ID" not in document_types:
            raise ValidationError("Add at least one Valid ID document for the RSBSA registration.")


ParcelRegistrationFormSet = formset_factory(
    ParcelRegistrationForm,
    formset=BaseRequiredRegistrationFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
CropRegistrationFormSet = formset_factory(
    CropRegistrationForm,
    formset=BaseRequiredRegistrationFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
DocumentRegistrationFormSet = formset_factory(
    DocumentRegistrationForm,
    formset=BaseDocumentRegistrationFormSet,
    extra=0,
    min_num=1,
    validate_min=True,
    can_delete=True,
)
