from django import forms
from django.contrib.auth.forms import UserCreationForm
from apps.authentication.models import CustomUser
from apps.common.forms import InlineValidationMixin, normalize_phone_digits


class AccountValidationMixin:
    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if not email:
            return email
        queryset = CustomUser.objects.filter(email__iexact=email)
        if getattr(self, "instance", None) and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("This email address is already linked to another account.")
        return email

    def clean_phone_number(self):
        phone_number = self.cleaned_data.get("phone_number", "").strip()
        normalized = normalize_phone_digits(phone_number)
        queryset = CustomUser.objects.exclude(phone_number="")
        if getattr(self, "instance", None) and self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if phone_number and any(normalize_phone_digits(value) == normalized for value in queryset.values_list("phone_number", flat=True)):
            raise forms.ValidationError("This phone number is already linked to another account.")
        return phone_number


class AccountForm(AccountValidationMixin, InlineValidationMixin, UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email", "phone_number", "role"):
            self.fields[name].required = True
    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            return username
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already in use. Please choose another username.")
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = True
        if commit:
            user.save()
        return user

    class Meta:
        model = CustomUser
        fields = ["username", "first_name", "last_name", "email", "phone_number", "role", "password1", "password2"]


class AccountUpdateForm(AccountValidationMixin, InlineValidationMixin, forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email", "phone_number", "role"):
            self.fields[name].required = True
    class Meta:
        model = CustomUser
        fields = ["username", "first_name", "last_name", "email", "phone_number", "role", "is_active"]
        labels = {"is_active": "Account is active"}

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            return username
        if CustomUser.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This username is already in use. Please choose another username.")
        return username
