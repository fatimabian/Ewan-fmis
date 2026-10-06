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
        users = get_user_model().objects.filter(is_active=True)
        if "@" in identifier:
            users = users.filter(email__iexact=identifier)
            return [user for user in users if user.has_usable_password()]

        phone = normalized_phone(identifier)
        if len(phone) < 10:
            return []
        return [
            user
            for user in users.exclude(phone_number="")
            if user.has_usable_password() and normalized_phone(user.phone_number) == phone
        ]


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
