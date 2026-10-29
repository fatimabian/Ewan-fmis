from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, UserCreationForm
from apps.common.forms import (
    InlineValidationMixin,
    normalize_person_name,
    normalize_phone_digits,
)


class LoginForm(InlineValidationMixin, AuthenticationForm):
    username = AuthenticationForm.base_fields["username"]
    username.widget.attrs.update(
        {"class": "form-control", "placeholder": "Username", "autocomplete": "username"}
    )
    password = AuthenticationForm.base_fields["password"]
    password.widget.attrs.update(
        {"class": "form-control", "placeholder": "Password", "autocomplete": "current-password"}
    )
    remember_me = forms.BooleanField(
        required=False,
        label="Remember me",
        widget=forms.CheckboxInput(attrs={"class": "remember-checkbox"}),
    )


class StaffRegistrationForm(InlineValidationMixin, UserCreationForm):
    """Public application form; saving never grants FMIS access."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("first_name", "last_name", "email", "phone_number"):
            self.fields[name].required = True
        self.fields["password1"].help_text = ""
        self.fields["password2"].help_text = ""
        placeholders = {
            "username": "Choose a username",
            "first_name": "First name",
            "last_name": "Last name",
            "email": "Office email address",
            "phone_number": "09XXXXXXXXX",
            "password1": "Create a password",
            "password2": "Confirm password",
        }
        for name, field in self.fields.items():
            field.widget.attrs.update(
                {
                    "class": "form-control",
                    "placeholder": placeholders.get(name, field.label),
                    "autocomplete": (
                        "new-password" if name.startswith("password") else name
                    ),
                }
            )

    def clean_username(self):
        username = self.cleaned_data.get("username", "").strip()
        if get_user_model().objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already in use.")
        return username

    def clean_first_name(self):
        return normalize_person_name(self.cleaned_data.get("first_name", ""))

    def clean_last_name(self):
        return normalize_person_name(self.cleaned_data.get("last_name", ""))

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email address is already registered.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number", "").strip()
        if not phone.isdigit() or len(phone) != 11 or not phone.startswith("09"):
            raise forms.ValidationError("Enter 11 digits beginning with 09.")
        normalized = normalize_phone_digits(phone)
        if any(
            normalize_phone_digits(value) == normalized
            for value in get_user_model().objects.exclude(phone_number="").values_list(
                "phone_number", flat=True
            )
        ):
            raise forms.ValidationError("This phone number is already registered.")
        return phone

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = "STAFF"
        user.is_active = False
        user.activation_pending = False
        user.approval_status = user.APPROVAL_PENDING
        if commit:
            user.save()
        return user

    class Meta:
        model = get_user_model()
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "password1",
            "password2",
        )
class ActivationOTPForm(InlineValidationMixin, forms.Form):
    code = forms.CharField(
        label="Six-digit verification code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
                "autofocus": True,
            }
        ),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the six-digit code from the email.")
        return code


class MFASetupForm(ActivationOTPForm):
    code = forms.CharField(
        label="Six-digit authenticator code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
                "autofocus": True,
            }
        ),
    )
    trust_device = forms.BooleanField(
        required=False,
        initial=True,
        label="Trust this private office browser for 30 days",
        widget=forms.CheckboxInput(attrs={"class": "remember-checkbox"}),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the six-digit code from your authenticator app.")
        return code


class MFAVerificationForm(InlineValidationMixin, forms.Form):
    code = forms.CharField(
        label="Authenticator or recovery code",
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "placeholder": "Six-digit code",
                "autofocus": True,
            }
        ),
    )
    trust_device = forms.BooleanField(
        required=False,
        initial=True,
        label="Trust this private office browser for 30 days",
        widget=forms.CheckboxInput(attrs={"class": "remember-checkbox"}),
    )

    def clean_code(self):
        return self.cleaned_data["code"].strip()


def normalized_phone(value):
    """Return a comparison-friendly Philippine phone number."""
    return normalize_phone_digits(value)


class IdentifierPasswordResetForm(InlineValidationMixin, forms.Form):
    identifier = forms.CharField(
        label="Email address or phone number",
        max_length=254,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "email tel",
                "placeholder": "name@example.com or 09XXXXXXXXX",
            }
        ),
    )

    def matching_users(self):
        identifier = self.cleaned_data["identifier"].strip()
        users = get_user_model().objects.filter(is_active=True).order_by("pk")
        if "@" in identifier:
            user = next(
                (
                    item
                    for item in users.filter(email__iexact=identifier)
                    if item.has_usable_password()
                ),
                None,
            )
            return [user] if user else []

        phone = normalized_phone(identifier)
        if len(phone) < 10:
            return []
        user = next(
            (
                item
                for item in users.exclude(phone_number="")
                if item.has_usable_password()
                and normalized_phone(item.phone_number) == phone
            ),
            None,
        )
        return [user] if user else []


class PasswordRecoveryOTPForm(ActivationOTPForm):
    pass


class RecoverySetPasswordForm(InlineValidationMixin, SetPasswordForm):
    """Django's password validators with landing-modal friendly widgets."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {"placeholder": "New password", "autocomplete": "new-password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"placeholder": "Confirm new password", "autocomplete": "new-password"}
        )
