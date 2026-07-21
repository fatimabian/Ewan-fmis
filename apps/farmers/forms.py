from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory

from apps.crops.models import CropRecord
from apps.common.constants import ROSARIO_BARANGAY_CHOICES
from apps.common.forms import InlineValidationMixin
from apps.farm_parcels.models import FarmParcel

from .models import Farmer, FarmerDocument


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
            if isinstance(field.widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            field.widget.attrs.setdefault("class", "form-control")


class FarmerRegistrationForm(StyledFormMixin, forms.ModelForm):
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES, required=True)
    activities = forms.MultipleChoiceField(
        choices=ACTIVITY_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Livelihood activities (select all that apply)",
    )
    consent_given = forms.BooleanField(
        required=True,
        label="I confirm the information is correct and the farmer gave consent for RSBSA registration and data processing.",
    )

    class Meta:
        model = Farmer
        fields = [
            "last_name", "first_name", "middle_name", "extension_name", "sex", "birth_date",
            "place_of_birth", "mother_maiden_name", "house_lot_purok", "street_sitio", "barangay",
            "city_municipality", "province", "region", "phone_number", "email", "civil_status",
            "spouse_name", "highest_education", "valid_id_type", "valid_id_number", "religion",
            "is_indigenous", "indigenous_group", "is_pwd", "is_four_ps", "photo", "livelihood",
            "activities", "remarks", "consent_given", "location_coordinates",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "sex": forms.Select,
            "civil_status": forms.Select,
            "livelihood": forms.Select,
            "photo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "location_coordinates": forms.TextInput(attrs={"placeholder": "e.g., 13.8467, 121.2060"}),
            "remarks": forms.Textarea(attrs={"rows": 3, "maxlength": 1000, "placeholder": "Optional internal remarks for agricultural service follow-up"}),
        }
        labels = {
            "extension_name": "Name extension (Jr., Sr., III)",
            "house_lot_purok": "House / Lot / Purok",
            "street_sitio": "Street / Sitio / Subdivision",
            "is_indigenous": "Member of an Indigenous People / ICC",
            "indigenous_group": "Indigenous group name",
            "is_pwd": "Person with Disability (PWD)",
            "is_four_ps": "4Ps beneficiary",
            "location_coordinates": "Home map coordinates (optional)",
            "remarks": "Internal remarks (optional)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in (
            "sex", "birth_date", "place_of_birth", "mother_maiden_name", "barangay",
            "city_municipality", "province", "phone_number", "civil_status",
            "valid_id_type", "valid_id_number", "livelihood",
        ):
            if name in self.fields:
                self.fields[name].required = True
        self.apply_styles()
        if "activities" in self.fields and self.instance and self.instance.pk and self.instance.activities:
            self.initial["activities"] = self.instance.activities.split(",")

    def clean_activities(self):
        return ",".join(self.cleaned_data["activities"])

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
                self.add_error("valid_id_number", "This ID is already linked to another active farmer record.")
        if cleaned.get("is_indigenous") and not cleaned.get("indigenous_group"):
            self.add_error("indigenous_group", "Enter the Indigenous People or ICC group name.")
        if cleaned.get("civil_status") == "MARRIED" and not cleaned.get("spouse_name"):
            self.add_error("spouse_name", "Enter the spouse's name for a married registrant.")
        return cleaned


class FarmerProfileUpdateForm(FarmerRegistrationForm):
    consent_given = forms.BooleanField(required=False, widget=forms.HiddenInput)

    class Meta(FarmerRegistrationForm.Meta):
        fields = [field for field in FarmerRegistrationForm.Meta.fields if field not in {"livelihood", "activities"}]


class ParcelRegistrationForm(StyledFormMixin, forms.ModelForm):
    not_applicable = forms.BooleanField(
        required=False,
        label="N/A - no parcel information yet; update it later in Farm Parcel",
    )
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES, required=False)
    farm_type = forms.CharField(
        max_length=30,
        required=False,
        label="Farm type",
        widget=forms.TextInput(attrs={"placeholder": "Remarks"}),
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
        self.order_fields(["not_applicable"] + [name for name in self.fields if name != "not_applicable"])
        required_later = ("barangay", "area_hectares", "ownership_type", "land_type", "farm_type")
        for name in required_later:
            self.fields[name].required = False
            self.fields[name].widget.attrs["data-step-required"] = "true"
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("not_applicable"):
            return cleaned
        for name in ("barangay", "area_hectares", "ownership_type", "land_type", "farm_type"):
            if not cleaned.get(name):
                self.add_error(name, "Complete this field or choose the N/A option above.")
        return cleaned


class CropRegistrationForm(StyledFormMixin, forms.ModelForm):
    not_applicable = forms.BooleanField(
        required=False,
        label="N/A - no crop information yet; update it later in Crops",
    )
    parcel_number = forms.IntegerField(min_value=1, required=False, label="Parcel number")

    class Meta:
        model = CropRecord
        exclude = ["parcel"]
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
        self.order_fields(["not_applicable"] + [name for name in self.fields if name != "not_applicable"])
        for name in ("parcel_number", "crop_type", "area_hectares"):
            self.fields[name].required = False
            self.fields[name].widget.attrs["data-step-required"] = "true"
        self.apply_styles()

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("not_applicable"):
            return cleaned
        for name in ("parcel_number", "crop_type", "area_hectares"):
            if not cleaned.get(name):
                self.add_error(name, "Complete this field or choose the N/A option above.")
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
            raise ValidationError("The file contents do not match the selected PDF or image format.")
        return upload


class BaseRequiredRegistrationFormSet(BaseFormSet):
    """Validate every row the browser says exists, including user-added rows."""

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
    ParcelRegistrationForm, formset=BaseRequiredRegistrationFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=True,
)
CropRegistrationFormSet = formset_factory(
    CropRegistrationForm, formset=BaseRequiredRegistrationFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=True,
)
DocumentRegistrationFormSet = formset_factory(
    DocumentRegistrationForm, formset=BaseDocumentRegistrationFormSet,
    extra=0, min_num=1, validate_min=True, can_delete=True,
)
