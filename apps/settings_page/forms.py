import re

from django import forms

from apps.authentication.models import CustomUser
from apps.common.forms import InlineValidationMixin, normalize_phone_digits


class ProfileForm(InlineValidationMixin, forms.Form):
    # Optional on the user model and on legacy FMIS accounts. An unchanged
    # profile must not fail simply because these values were never supplied.
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    phone_number = forms.CharField(max_length=20, required=False)
    profile_photo = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp"}),
    )
    remove_profile_photo = forms.BooleanField(required=False)
    theme = forms.ChoiceField(
        choices=[("system", "System (Recommended)"), ("light", "Light"), ("dark", "Dark")]
    )
    primary_color = forms.CharField(max_length=7)
    in_app_notifications = forms.BooleanField(required=False)
    automated_backups = forms.BooleanField(required=False)

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            return email
        queryset = CustomUser.objects.filter(email__iexact=email)
        if self.user:
            queryset = queryset.exclude(pk=self.user.pk)
        if queryset.exists():
            raise forms.ValidationError("This email address is already linked to another account.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get("phone_number", "").strip()
        normalized = normalize_phone_digits(phone_number)
        queryset = CustomUser.objects.exclude(phone_number="")
        if self.user:
            queryset = queryset.exclude(pk=self.user.pk)
        if phone_number and any(
            normalize_phone_digits(value) == normalized
            for value in queryset.values_list("phone_number", flat=True)
        ):
            raise forms.ValidationError("This phone number is already linked to another account.")
        return phone_number

    def clean_primary_color(self):
        color = self.cleaned_data.get("primary_color", "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise forms.ValidationError("Choose a valid interface color.")
        return color.lower()
