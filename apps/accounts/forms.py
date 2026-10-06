from django import forms
from django.contrib.auth.forms import UserCreationForm
from apps.authentication.models import CustomUser
from apps.common.forms import InlineValidationMixin, normalize_phone_digits
from apps.common.constants import ASSIGNABLE_ROLE_CHOICES, ROLE_CHOICES, ROLE_STAFF


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
        if phone_number and any(
            normalize_phone_digits(value) == normalized
            for value in queryset.values_list("phone_number", flat=True)
        ):
            raise forms.ValidationError("This phone number is already linked to another account.")
        return phone_number


class AccountForm(AccountValidationMixin, InlineValidationMixin, UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = False
        self.fields["last_name"].required = False
        self.fields["email"].required = True
        self.fields["phone_number"].required = True
        self.fields["password1"].label = "Password"
        self.fields["password2"].label = "Confirm Password"
        self.fields["password1"].help_text = ""
        self.fields["password2"].help_text = ""

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            return username
        if CustomUser.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(
                "This username is already in use. Please choose another username."
            )
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = ROLE_STAFF
        user.is_active = False
        user.activation_pending = True
        if commit:
            user.save()
        return user

    class Meta:
        model = CustomUser
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "password1",
            "password2",
        ]


class AccountUpdateForm(AccountValidationMixin, InlineValidationMixin, forms.ModelForm):
    is_active = forms.TypedChoiceField(
        choices=(
            ("True", "Active"),
            ("False", "Inactive"),
        ),
        coerce=lambda value: value in (True, "True", "true", "1", "on"),
        empty_value=None,
        label="Account Status",
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = False
        self.fields["last_name"].required = False
        for name in ("email", "phone_number", "role"):
            self.fields[name].required = True
        current_role = getattr(self.instance, "role", None)
        if current_role and current_role not in dict(ASSIGNABLE_ROLE_CHOICES):
            self.fields["role"].choices = ROLE_CHOICES
        else:
            self.fields["role"].choices = ASSIGNABLE_ROLE_CHOICES

    class Meta:
        model = CustomUser
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "role",
            "is_active",
        ]

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if not username:
            return username
        if (
            CustomUser.objects.filter(username__iexact=username)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise forms.ValidationError(
                "This username is already in use. Please choose another username."
            )
        return username

    def clean_is_active(self):
        is_active = self.cleaned_data.get("is_active", False)
        if self.instance.activation_pending and is_active:
            raise forms.ValidationError(
                "This new account must complete first-login email verification before activation."
            )
        return is_active
