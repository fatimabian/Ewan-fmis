import re
from datetime import date
from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

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
    MultipleFileInput,
    MultipleImageField,
    RequiredYesNoField,
    YesNoNAField,
    add_other_crop_field,
    resolve_other_crop,
)
from apps.farm_parcels.models import FarmParcel

from .models import Farmer, FarmerDocument, FarmerUpdateHistory


LETTERS_ONLY_PATTERN = re.compile(r"^[^\W\d_]+(?:[ .,'’\-]+[^\W\d_]+)*\.?$", re.UNICODE)
SAFE_MIXED_PATTERN = re.compile(r"^[\w .,:#&'’/()\-]+$", re.UNICODE)
HTML_LETTERS_PATTERN = r"[A-Za-zÑñÁÉÍÓÚÜáéíóúü .,'’\-]+"
HTML_MIXED_PATTERN = r"[A-Za-z0-9ÑñÁÉÍÓÚÜáéíóúü .,:#&'’_/()\-]+"


def configure_registration_inputs(form, *, letters=(), digits=(), mixed=()):
    """Describe allowed input to browsers while server validation remains authoritative."""

    for name in letters:
        field = form.fields.get(name)
        if not field or isinstance(field.widget, forms.HiddenInput):
            continue
        field.widget.attrs.update(
            {
                "data-input-kind": "letters",
                "pattern": HTML_LETTERS_PATTERN,
                "title": "Use letters only. Spaces, apostrophes, periods, commas, and hyphens are allowed.",
            }
        )
    for name in digits:
        field = form.fields.get(name)
        if not field or isinstance(field.widget, forms.HiddenInput):
            continue
        field.widget.attrs.update(
            {
                "data-input-kind": "digits",
                "inputmode": "numeric",
                "pattern": r"[0-9]+",
                "title": "Use numbers only.",
            }
        )
    for name in mixed:
        field = form.fields.get(name)
        if not field or isinstance(field.widget, forms.HiddenInput):
            continue
        field.widget.attrs.update(
            {
                "data-input-kind": "safe-mixed",
                "pattern": HTML_MIXED_PATTERN,
                "title": "Use only letters, numbers, spaces, and ordinary punctuation.",
            }
        )


def validate_registration_inputs(form, cleaned, *, letters=(), digits=(), mixed=()):
    """Reject invalid characters even when browser-side checks are bypassed."""

    for name in letters:
        value = cleaned.get(name)
        if value and not LETTERS_ONLY_PATTERN.fullmatch(value):
            form.add_error(
                name,
                "Use letters only. Spaces, apostrophes, periods, commas, and hyphens are allowed.",
            )
    for name in digits:
        value = cleaned.get(name)
        if value and not value.isdecimal():
            form.add_error(name, "Use numbers only. Letters and symbols are not allowed.")
    for name in mixed:
        value = cleaned.get(name)
        if value and not SAFE_MIXED_PATTERN.fullmatch(value):
            form.add_error(
                name,
                "Use only letters, numbers, spaces, and ordinary punctuation.",
            )
    return cleaned

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

VALID_ID_CHOICES = [
    ("", "Select an accepted proof of identity"),
    ("Birth Certificate", "Birth Certificate"),
    ("National ID", "PhilID / National ID / ePhilID"),
    ("Passport", "Passport"),
    ("Driver's License", "Driver's License"),
    ("e-Card / UMID", "e-Card / UMID"),
    ("SSS ID", "SSS ID"),
    ("PRC ID", "PRC ID"),
    ("IBP ID", "IBP ID"),
    ("NBI Clearance", "NBI Clearance"),
    ("Voter's ID", "Voter's ID"),
    ("TIN ID", "TIN ID"),
    ("Pag-IBIG ID", "Pag-IBIG ID"),
    ("Senior Citizen ID", "Senior Citizen ID"),
    ("PWD ID", "PWD ID"),
    ("Solo Parent ID", "Solo Parent ID"),
    ("4Ps ID", "4Ps ID"),
    ("Postal ID", "Postal ID"),
    ("PhilHealth ID", "PhilHealth ID"),
    ("City / Municipal / Barangay ID", "City / Municipal / Barangay ID"),
    ("Employee / School ID", "Employee / School ID"),
]

VALID_ID_RULES = {
    "National ID": (r"\d{16}", "Enter the 16-digit PhilSys Card Number (PCN)."),
    "Passport": (r"[A-Z]{1,2}\d{7}", "Use 1 or 2 letters followed by 7 numbers."),
    "Driver's License": (
        r"[A-Z]\d{2}-?\d{2}-?\d{6}",
        "Use the Philippine driver's license format, for example N01-12-123456.",
    ),
    "e-Card / UMID": (r"\d{12}", "Enter the 12-digit CRN shown on the card."),
    "SSS ID": (r"\d{10}", "Enter the 10-digit SSS number."),
    "PRC ID": (r"\d{7}", "Enter the 7-digit PRC license number."),
    "IBP ID": (r"\d{4,8}", "Enter the 4 to 8-digit IBP roll number."),
    "TIN ID": (r"\d{12}", "Enter the 12-digit TIN, including the branch code."),
    "Pag-IBIG ID": (r"\d{12}", "Enter the 12-digit Pag-IBIG MID number."),
    "4Ps ID": (r"\d{12}", "Enter the 12-digit 4Ps household ID number."),
    "PhilHealth ID": (r"\d{12}", "Enter the 12-digit PhilHealth identification number."),
}

GENERIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .#()/\-]{2,39}$")
RSBSA_NUMBER_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{2}-\d{3}-\d{6}$")
MONTH_CHOICES = (
    ("", "Select month"),
    ("January", "January"),
    ("February", "February"),
    ("March", "March"),
    ("April", "April"),
    ("May", "May"),
    ("June", "June"),
    ("July", "July"),
    ("August", "August"),
    ("September", "September"),
    ("October", "October"),
    ("November", "November"),
    ("December", "December"),
)


class StyledFormMixin(InlineValidationMixin):
    def apply_styles(self):
        for field in self.fields.values():
            if isinstance(
                field.widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple)
            ):
                continue
            field.widget.attrs.setdefault("class", "form-control")


class FarmerRegistrationForm(StyledFormMixin, forms.ModelForm):
    LETTER_FIELDS = (
        "last_name",
        "first_name",
        "middle_name",
        "extension_name",
        "place_of_birth",
        "mother_maiden_name",
        "spouse_name",
        "religion",
        "indigenous_group",
    )
    DIGIT_FIELDS = ("philsys_pcn", "philsys_trn")
    MIXED_FIELDS = (
        "house_lot_purok",
        "street_sitio",
        "highest_education",
        "fca_membership",
    )
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES, required=True)
    valid_id_type = forms.ChoiceField(
        choices=VALID_ID_CHOICES,
        required=False,
        label="Valid ID type (optional)",
    )
    is_indigenous = YesNoNAField(label="Member of an Indigenous People / ICC")
    is_pwd = YesNoNAField(label="Person with Disability (PWD)")
    is_four_ps = YesNoNAField(label="4Ps beneficiary")
    philsys_registered = YesNoNAField(
        required=False,
        label="Registered in PhilSys / National ID",
        choices=(("", "Select Yes or No"), ("True", "Yes"), ("False", "No")),
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
        configure_registration_inputs(
            self,
            letters=self.LETTER_FIELDS,
            digits=self.DIGIT_FIELDS,
            mixed=self.MIXED_FIELDS,
        )
        if "phone_number" in self.fields:
            self.fields["phone_number"].widget.attrs["data-input-kind"] = "digits"
        if "phone_number" in self.fields and not (self.instance and self.instance.pk):
            self.initial.setdefault("phone_number", "09")
        self.fields["is_indigenous"].widget.attrs["data-indigenous-choice"] = "true"
        self.fields["indigenous_group"].widget.attrs["data-indigenous-group"] = "true"
        self.fields["valid_id_type"].widget.attrs["data-valid-id-type"] = "true"
        self.fields["valid_id_number"].widget.attrs.update(
            {
                "data-valid-id-number": "true",
                "autocomplete": "off",
                "placeholder": "Choose an ID type first",
                "aria-describedby": "valid-id-format-help",
            }
        )
        self.fields["valid_id_number"].help_text = (
            "Optional when the farmer has no valid ID. If an ID type is selected, enter its number."
        )
        today = timezone.localdate()
        try:
            oldest_allowed_child = today.replace(year=today.year - 11)
        except ValueError:
            oldest_allowed_child = date(today.year - 11, 2, 28)
        self.fields["birth_date"].widget.attrs.update(
            {
                "max": oldest_allowed_child.isoformat(),
                "title": "The farmer must be at least 11 years old.",
            }
        )

    def clean_birth_date(self):
        birth_date = self.cleaned_data.get("birth_date")
        if not birth_date:
            return birth_date

        today = timezone.localdate()
        if birth_date > today:
            raise ValidationError("Birth date cannot be today, tomorrow, or any future date.")

        age = today.year - birth_date.year - (
            (today.month, today.day) < (birth_date.month, birth_date.day)
        )
        if age <= 10:
            raise ValidationError("The farmer must be at least 11 years old.")
        return birth_date

    def clean_phone_number(self):
        value = (self.cleaned_data.get("phone_number") or "").strip()
        if not value:
            return value
        if not re.fullmatch(r"09\d{9}", value):
            raise ValidationError(
                "Use numbers only and enter 11 digits starting with 09 (for example, 09171234567)."
            )
        return value

    def clean(self):
        cleaned = super().clean()
        validate_registration_inputs(
            self,
            cleaned,
            letters=self.LETTER_FIELDS,
            digits=self.DIGIT_FIELDS,
            mixed=self.MIXED_FIELDS,
        )
        valid_id_type = cleaned.get("valid_id_type")
        valid_id_number = (cleaned.get("valid_id_number") or "").strip().upper()
        cleaned["valid_id_number"] = valid_id_number
        original_id_type = self.initial.get("valid_id_type", "")
        original_id_number = str(self.initial.get("valid_id_number", "") or "").strip().upper()
        id_was_changed = (
            not self.instance.pk
            or valid_id_type != original_id_type
            or valid_id_number != original_id_number
        )
        if valid_id_type and not valid_id_number:
            self.add_error("valid_id_number", "Enter the number shown on the selected ID.")
        elif valid_id_number and not valid_id_type:
            self.add_error("valid_id_type", "Select the type of ID for this number.")
        if valid_id_type and valid_id_number and id_was_changed:
            rule = VALID_ID_RULES.get(valid_id_type)
            if rule and not re.fullmatch(rule[0], valid_id_number):
                self.add_error("valid_id_number", rule[1])
            elif not rule and not GENERIC_ID_PATTERN.fullmatch(valid_id_number):
                self.add_error(
                    "valid_id_number",
                    "Enter 3 to 40 letters and numbers exactly as shown on the ID. Spaces, hyphens, slashes, periods, parentheses, and # are allowed.",
                )
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
    LETTER_FIELDS = FarmerRegistrationForm.LETTER_FIELDS + ("agriculturist_name",)
    MIXED_FIELDS = FarmerRegistrationForm.MIXED_FIELDS + (
        "transaction_code",
    )
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
        # Older clients and saved drafts may omit the new tri-state fields.
        # Preserve the stored value on updates instead of silently replacing it.
        for name in ("is_indigenous", "is_pwd", "is_four_ps"):
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        if self.is_bound and self.instance and self.instance.pk:
            for name in ("is_indigenous", "is_pwd", "is_four_ps"):
                if self.add_prefix(name) not in self.data:
                    cleaned[name] = getattr(self.instance, name)
        return cleaned


class FarmerRegistrationStatusForm(StyledFormMixin, forms.ModelForm):
    """Office-controlled RSBSA processing; this is not a registrant Slip A request."""

    class Meta:
        model = Farmer
        fields = ["registration_status", "rsbsa_number"]
        labels = {
            "registration_status": "Registration status",
            "rsbsa_number": "Official RSBSA ID / Reference Code",
        }
        help_texts = {
            "registration_status": (
                "Use Skipped when requirements need correction. Select Completed after the "
                "office accepts the registration."
            ),
            "rsbsa_number": (
                "Required only when Completed. Use the official 15-digit DA/FFRS number: "
                "00-00-00-000-000000. Letters are not allowed."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rsbsa_number"].required = False
        self.fields["rsbsa_number"].widget.attrs.update(
            {
                "autocomplete": "off",
                "placeholder": "00-00-00-000-000000",
                "data-rsbsa-id": "true",
                "inputmode": "numeric",
                "maxlength": "19",
                "pattern": r"(?:[0-9]{15}|[0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{3}-[0-9]{6})",
                "title": "Enter 15 digits in the format 00-00-00-000-000000.",
            }
        )
        self.fields["registration_status"].widget.attrs["data-registration-status"] = "true"
        if self.instance and self.instance.pk and self.instance.registration_status == "COMPLETED":
            self.fields["registration_status"].choices = [("COMPLETED", "Completed")]
        self.apply_styles()

    def clean_rsbsa_number(self):
        value = (self.cleaned_data.get("rsbsa_number") or "").strip()
        if not value:
            return None
        if re.search(r"[^0-9\s-]", value):
            raise ValidationError("Use numbers only. Letters and other symbols are not allowed.")
        digits = re.sub(r"[\s-]", "", value)
        if len(digits) != 15:
            raise ValidationError(
                "Enter the complete 15-digit official RSBSA number."
            )
        normalized = (
            f"{digits[0:2]}-{digits[2:4]}-{digits[4:6]}-"
            f"{digits[6:9]}-{digits[9:15]}"
        )
        if not RSBSA_NUMBER_PATTERN.fullmatch(normalized):
            raise ValidationError("Use the official format 00-00-00-000-000000.")
        return normalized

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("registration_status")
        rsbsa_number = cleaned.get("rsbsa_number")
        if status == "COMPLETED" and not rsbsa_number:
            self.add_error(
                "rsbsa_number",
                "Enter the official RSBSA ID before marking this registration as Completed.",
            )
        elif status and status != "COMPLETED" and rsbsa_number:
            self.add_error(
                "rsbsa_number",
                "The official RSBSA ID can only be entered for a Completed registration.",
            )
        return cleaned


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
    LETTER_FIELDS = ("land_owner_name",)
    MIXED_FIELDS = (
        "ownership_document_other",
        "land_owner_rsbsa_number",
        "georef_id",
    )
    barangay = forms.ChoiceField(choices=ROSARIO_BARANGAY_CHOICES, required=True)
    is_active = RequiredYesNoField(label="Currently cultivated / active?")
    farm_type = forms.CharField(
        max_length=180,
        required=True,
        label="Farm type",
        widget=forms.TextInput(
            attrs={"placeholder": "Enter farm type or brief office remarks"}
        ),
    )
    field_photos = MultipleImageField(
        required=False,
        label="Field photos",
        help_text="Select one or more current photos of this farm parcel.",
        widget=MultipleFileInput(
            attrs={"accept": "image/png,image/jpeg,image/webp", "multiple": True}
        ),
    )
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
    land_owner_registered_rsbsa = forms.TypedChoiceField(
        choices=(("", "Select Yes or No"), ("True", "Yes"), ("False", "No")),
        coerce=lambda value: {"True": True, "False": False}.get(value),
        empty_value=None,
        required=False,
        label="Land owner is registered in RSBSA",
    )

    class Meta:
        model = FarmParcel
        exclude = ["farmer", "created_at", "parcel_name", "remarks", "is_rsbsa_recorded"]
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
        for name in ("land_owner_name", "land_owner_registered_rsbsa", "land_owner_rsbsa_number"):
            self.fields[name].widget.attrs["data-owner-detail"] = "true"
        self.fields["ownership_type"].widget.attrs["data-ownership-type"] = "true"
        self.apply_styles()
        configure_registration_inputs(
            self,
            letters=self.LETTER_FIELDS,
            mixed=self.MIXED_FIELDS,
        )

    def clean(self):
        cleaned = super().clean()
        validate_registration_inputs(
            self,
            cleaned,
            letters=self.LETTER_FIELDS,
            mixed=self.MIXED_FIELDS,
        )
        for name in ("barangay", "area_hectares", "ownership_type", "land_type", "farm_type"):
            if not cleaned.get(name):
                self.add_error(name, "Complete this field for the farm parcel.")
        ownership_type = cleaned.get("ownership_type")
        owner_details_apply = ownership_type in {"TENANT", "LEASED", "OTHER"}
        if not owner_details_apply:
            cleaned["land_owner_name"] = ""
            cleaned["land_owner_registered_rsbsa"] = None
            cleaned["land_owner_rsbsa_number"] = ""
        else:
            if not cleaned.get("land_owner_name"):
                self.add_error("land_owner_name", "Enter the land owner's name.")
            if cleaned.get("land_owner_registered_rsbsa") is True and not cleaned.get(
                "land_owner_rsbsa_number"
            ):
                self.add_error(
                    "land_owner_rsbsa_number",
                    "Enter the land owner's RSBSA number when Yes is selected.",
                )
            if cleaned.get("land_owner_registered_rsbsa") is not True:
                cleaned["land_owner_rsbsa_number"] = ""
        return cleaned


class CropRegistrationForm(StyledFormMixin, forms.ModelForm):
    MIXED_FIELDS = ("other_crop_name",)
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
    cropping_start_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        required=False,
        label="Cropping schedule start",
    )
    cropping_end_month = forms.ChoiceField(
        choices=MONTH_CHOICES,
        required=False,
        label="Cropping schedule end",
    )

    class Meta:
        model = CropRecord
        exclude = [
            "parcel",
            "cropping_schedule",
            "harvest_date",
            "is_active",
            "archived_at",
            "archived_by",
            "image",
        ]
        labels = {
            "crop_type": "Crop / Commodity",
            "number_of_heads": "Number of heads / trees (if applicable)",
            "is_organic": "Organic production",
        }
        widgets = {
            "area_hectares": forms.NumberInput(attrs={"min": "0.01", "step": "0.01"}),
            "planting_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        add_other_crop_field(self)
        schedule = self.initial.get("cropping_schedule") or getattr(
            self.instance, "cropping_schedule", ""
        )
        if schedule and " - " in schedule:
            start_month, end_month = schedule.split(" - ", 1)
            self.initial.setdefault("cropping_start_month", start_month)
            self.initial.setdefault("cropping_end_month", end_month)
        self.order_fields(
            [
                "parcel_number",
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
                    "parcel_number",
                    "crop_type",
                    "other_crop_name",
                    "cropping_start_month",
                    "cropping_end_month",
                }
            ]
        )
        for name in (
            "parcel_number",
            "crop_type",
            "area_hectares",
            "cropping_start_month",
            "cropping_end_month",
        ):
            self.fields[name].required = False
            self.fields[name].widget.attrs["data-step-required"] = "true"
        self.apply_styles()
        configure_registration_inputs(self, mixed=self.MIXED_FIELDS)

    def clean(self):
        cleaned = super().clean()
        validate_registration_inputs(self, cleaned, mixed=self.MIXED_FIELDS)
        resolve_other_crop(self, cleaned)
        for name in (
            "parcel_number",
            "crop_type",
            "area_hectares",
            "cropping_start_month",
            "cropping_end_month",
        ):
            if not cleaned.get(name):
                self.add_error(name, "Complete this field for the crop or commodity.")
        start_month = cleaned.get("cropping_start_month")
        end_month = cleaned.get("cropping_end_month")
        cleaned["cropping_schedule"] = (
            f"{start_month} - {end_month}" if start_month and end_month else ""
        )
        return cleaned


class DocumentRegistrationForm(StyledFormMixin, forms.Form):
    MIXED_FIELDS = ("description",)
    document_type = forms.ChoiceField(choices=FarmerDocument.DOCUMENT_TYPE_CHOICES)
    description = forms.CharField(max_length=180, required=False)
    file = forms.FileField(help_text="JPG, PNG, or PDF; maximum 5 MB")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_styles()
        configure_registration_inputs(self, mixed=self.MIXED_FIELDS)
        self.fields["file"].widget.attrs["accept"] = ".jpg,.jpeg,.png,.pdf"
        self.fields["description"].widget.attrs["placeholder"] = "Briefly describe the document"

    def clean(self):
        cleaned = super().clean()
        return validate_registration_inputs(self, cleaned, mixed=self.MIXED_FIELDS)

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
        active_documents = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if not active_documents:
            raise ValidationError("Add at least one supporting document for the registration.")


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
