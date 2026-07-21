import re
from datetime import date
from pathlib import Path

from django import forms
from django.core.exceptions import NON_FIELD_ERRORS


CAPITALIZATION_EXCLUSIONS = {
    "username", "password", "password1", "password2", "old_password",
    "new_password1", "new_password2", "email", "phone_number", "identifier",
    "otp", "code", "badge_color", "primary_color", "coordinates",
    "location_coordinates", "georef_id", "valid_id_number", "rsbsa_number",
}


def capitalize_first_letter(value):
    """Uppercase the first alphabetic character without changing the rest."""
    for index, character in enumerate(value):
        if character.isalpha():
            return value[:index] + character.upper() + value[index + 1:]
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
            if not isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple, forms.HiddenInput)):
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
                name for name, field in self.fields.items()
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
            upload = cleaned.get(name)
            if not upload:
                continue
            if getattr(upload, "size", 0) > 8 * 1024 * 1024:
                self.add_error(name, "Upload a file that is 8 MB or smaller.")
            extension = Path(getattr(upload, "name", "")).suffix.lower()
            allowed = allowed_image_extensions if isinstance(field, forms.ImageField) else allowed_document_extensions
            if extension not in allowed:
                self.add_error(name, "Upload a PDF, PNG, or JPG file." if not isinstance(field, forms.ImageField) else "Upload a PNG, JPG, or WEBP image.")
        return cleaned
