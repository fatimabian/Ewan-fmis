import re
from datetime import date
from pathlib import Path

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.core.files.uploadedfile import UploadedFile


OTHER_CROP_VALUE = "Other Crop / Commodity"


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Validate several parcel photos submitted through one file input."""

    widget = MultipleFileInput

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        files = [upload for upload in files if upload]
        if not files:
            if self.required:
                raise forms.ValidationError(self.error_messages["required"], code="required")
            return []
        if len(files) > 12:
            raise forms.ValidationError("Upload no more than 12 field photos at one time.")
        cleaned = [super(MultipleImageField, self).clean(upload, initial) for upload in files]
        for upload in cleaned:
            if upload.size > 8 * 1024 * 1024:
                raise forms.ValidationError("Each field photo must be 8 MB or smaller.")
            if getattr(upload.image, "format", "").upper() not in {"PNG", "JPEG", "WEBP"}:
                raise forms.ValidationError("Upload PNG, JPG, or WEBP field photos only.")
        return cleaned


class RequiredYesNoField(forms.TypedChoiceField):
    """Required, readable Yes/No selection for official binary questions."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "choices",
            (("", "Select Yes or No"), ("True", "Yes"), ("False", "No")),
        )
        kwargs.setdefault("coerce", lambda value: value == "True")
        kwargs.setdefault("empty_value", None)
        kwargs.setdefault("required", True)
        super().__init__(*args, **kwargs)

    def clean(self, value):
        # Continue accepting the value submitted by the former checkbox UI.
        if value == "on":
            value = "True"
        return super().clean(value)


class YesNoNAField(forms.TypedChoiceField):
    """Legacy field name retained while presenting an unambiguous Yes/No choice."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "choices",
            (
                ("", "Select Yes or No"),
                ("True", "Yes"),
                ("False", "No"),
            ),
        )
        kwargs.setdefault(
            "coerce",
            lambda value: {"True": True, "False": False}.get(value),
        )
        kwargs.setdefault("empty_value", None)
        kwargs.setdefault("required", True)
        super().__init__(*args, **kwargs)

    def clean(self, value):
        # Continue accepting values submitted by the former checkbox UI.
        if value == "on":
            value = "True"
        elif value == "NA":
            # Backward-compatible handling for older saved drafts and clients;
            # the visible control now offers only Yes or No.
            value = "False"
        return super().clean(value)


def add_other_crop_field(form):
    """Add the conditional detail field used by every crop-entry workflow."""
    form.fields["other_crop_name"] = forms.CharField(
        required=False,
        min_length=2,
        max_length=100,
        label="Other crop / commodity name",
        help_text="Enter the specific crop or commodity planted, for example Dragon Fruit.",
        widget=forms.TextInput(
            attrs={
                "placeholder": "Enter the specific crop or commodity",
                "data-other-crop-detail": "true",
                "autocomplete": "off",
            }
        ),
    )


def resolve_other_crop(form, cleaned_data):
    """Replace the Other sentinel with the encoder's required specific crop name."""
    selected = cleaned_data.get("crop_type")
    other_name = (cleaned_data.get("other_crop_name") or "").strip()
    if selected == OTHER_CROP_VALUE:
        if not other_name:
            form.add_error(
                "other_crop_name",
                "Enter the specific crop or commodity when Other is selected.",
            )
        else:
            cleaned_data["crop_type"] = other_name
    return cleaned_data

CAPITALIZATION_EXCLUSIONS = {
    "username",
    "password",
    "password1",
    "password2",
    "old_password",
    "new_password1",
    "new_password2",
    "email",
    "phone_number",
    "identifier",
    "otp",
    "code",
    "badge_color",
    "primary_color",
    "coordinates",
    "location_coordinates",
    "georef_id",
    "valid_id_number",
    "rsbsa_number",
}


def capitalize_first_letter(value):
    """Uppercase the first alphabetic character without changing the rest."""
    for index, character in enumerate(value):
        if character.isalpha():
            return value[:index] + character.upper() + value[index + 1 :]
    return value


def normalize_phone_digits(value):
    """Normalize common Philippine mobile formats for identity comparisons."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("09") and len(digits) == 11:
        return "63" + digits[1:]
    if digits.startswith("9") and len(digits) == 10:
        return "63" + digits
    return digits


class InlineValidationMixin:
    """Shared normalization and accessible inline validation for every FMIS form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            if not isinstance(
                widget,
                (
                    forms.CheckboxInput,
                    forms.RadioSelect,
                    forms.CheckboxSelectMultiple,
                    forms.HiddenInput,
                ),
            ):
                widget.attrs.setdefault("class", "form-control")
            if self._should_capitalize(name, field):
                widget.attrs.setdefault("autocapitalize", "sentences")
                widget.attrs["data-capitalize-first"] = "true"
            if name == "phone_number":
                widget.attrs.setdefault("inputmode", "tel")
                widget.attrs.setdefault("autocomplete", "tel")

    @staticmethod
    def _should_capitalize(name, field):
        return (
            name not in CAPITALIZATION_EXCLUSIONS
            and isinstance(field, forms.CharField)
            and not isinstance(field, (forms.EmailField, forms.FileField))
            and not isinstance(field.widget, (forms.PasswordInput, forms.HiddenInput))
        )

    @staticmethod
    def _add_class(widget, class_name):
        classes = widget.attrs.get("class", "").split()
        if class_name not in classes:
            classes.append(class_name)
        widget.attrs["class"] = " ".join(classes)

    def add_error(self, field, error):
        """Keep errors added by views visually attached to their field too."""
        super().add_error(field, error)
        form_field = self.fields.get(field) if field else None
        if form_field:
            self._add_class(form_field.widget, "is-invalid")
            form_field.widget.attrs["aria-invalid"] = "true"

    def full_clean(self):
        super().full_clean()
        error_names = set(self.errors)
        if NON_FIELD_ERRORS in error_names:
            error_names.update(
                name
                for name, field in self.fields.items()
                if field.required and not isinstance(field.widget, forms.HiddenInput)
            )
        for name in error_names:
            field = self.fields.get(name)
            if not field:
                continue
            self._add_class(field.widget, "is-invalid")
            field.widget.attrs["aria-invalid"] = "true"

    def clean(self):
        cleaned = super().clean()
        for name, value in list(cleaned.items()):
            field = self.fields.get(name)
            if not field or not isinstance(value, str):
                continue
            value = value.strip()
            if self._should_capitalize(name, field):
                value = capitalize_first_letter(value)
            cleaned[name] = value

        phone = cleaned.get("phone_number")
        if phone:
            digits = normalize_phone_digits(phone)
            if not 7 <= len(digits) <= 15:
                self.add_error("phone_number", "Enter a valid phone number with 7 to 15 digits.")

        birth_date = cleaned.get("birth_date")
        if birth_date and birth_date > date.today():
            self.add_error("birth_date", "Date of birth cannot be in the future.")

        for coordinate_field in ("coordinates", "location_coordinates"):
            value = cleaned.get(coordinate_field)
            if not value:
                continue
            try:
                latitude, longitude = (float(part.strip()) for part in value.split(",", 1))
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise ValueError
            except (TypeError, ValueError):
                self.add_error(coordinate_field, "Enter coordinates as latitude, longitude.")

        allowed_document_extensions = {".pdf", ".png", ".jpg", ".jpeg"}
        allowed_image_extensions = {".png", ".jpg", ".jpeg", ".webp"}
        for name, field in self.fields.items():
            if not isinstance(field, forms.FileField):
                continue
            field_upload = cleaned.get(name)
            if not field_upload:
                continue
            uploads = field_upload if isinstance(field_upload, (list, tuple)) else [field_upload]
            for upload in uploads:
                # Existing form values are stored file references, not new uploads.
                # They may point to a legacy file that is no longer on disk.
                if not isinstance(upload, UploadedFile):
                    continue
                if getattr(upload, "size", 0) > 8 * 1024 * 1024:
                    self.add_error(name, "Upload a file that is 8 MB or smaller.")
                extension = Path(getattr(upload, "name", "")).suffix.lower()
                allowed = (
                    allowed_image_extensions
                    if isinstance(field, forms.ImageField)
                    else allowed_document_extensions
                )
                if extension not in allowed:
                    self.add_error(
                        name,
                        (
                            "Upload a PDF, PNG, or JPG file."
                            if not isinstance(field, forms.ImageField)
                            else "Upload a PNG, JPG, or WEBP image."
                        ),
                    )
        return cleaned
