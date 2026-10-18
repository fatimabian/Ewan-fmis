from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from apps.common.forms import InlineValidationMixin, normalize_phone_digits


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


class RecoverySetPasswordForm(SetPasswordForm):
    """Django's password validators with landing-modal friendly widgets."""

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {"placeholder": "New password", "autocomplete": "new-password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"placeholder": "Confirm new password", "autocomplete": "new-password"}
        )
