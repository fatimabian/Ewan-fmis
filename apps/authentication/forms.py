from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from apps.common.forms import InlineValidationMixin, normalize_phone_digits

class LoginForm(InlineValidationMixin, AuthenticationForm):
    username = AuthenticationForm.base_fields["username"]
    username.widget.attrs.update({"class": "form-control", "placeholder": "Username", "autocomplete": "username"})
    password = AuthenticationForm.base_fields["password"]
    password.widget.attrs.update({"class": "form-control", "placeholder": "Password", "autocomplete": "current-password"})
    remember_me = forms.BooleanField(
        required=False,
        label="Remember me",
        widget=forms.CheckboxInput(attrs={"class": "remember-checkbox"}),
    )


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

    def _email_reset_link(self, user, reset_url, from_email, subject_template_name, email_template_name):
        subject = "".join(render_to_string(subject_template_name).splitlines())
        body = render_to_string(
            email_template_name,
            {"user": user, "reset_url": reset_url, "site_name": "FMIS"},
        )
        EmailMultiAlternatives(subject, body, from_email, [user.email]).send()

    def save(
        self,
        domain_override=None,
        subject_template_name="authentication/password_reset_subject.txt",
        email_template_name="authentication/password_reset_email.txt",
        use_https=False,
        token_generator=default_token_generator,
        from_email=None,
        request=None,
        **kwargs,
    ):
        for user in self.matching_users():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = token_generator.make_token(user)
            reset_path = reverse(
                "authentication:password_reset_confirm",
                kwargs={"uidb64": uid, "token": token},
            )
            reset_url = request.build_absolute_uri(reset_path) if request else f"{'https' if use_https else 'http'}://{domain_override}{reset_path}"

            if user.email:
                self._email_reset_link(
                    user,
                    reset_url,
                    from_email or settings.DEFAULT_FROM_EMAIL,
                    subject_template_name,
                    email_template_name,
                )

