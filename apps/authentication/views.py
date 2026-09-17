import hashlib
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import FormView, TemplateView

from apps.activity_logs.services import record_event, record_request_event
from apps.common.middleware import REMEMBER_UNTIL_SESSION_KEY

from .activation import (
    ACTIVATION_MAX_ATTEMPTS,
    clear_activation_challenge,
    get_activation_challenge,
    masked_email,
    send_activation_code,
    verify_activation_code,
)
from .forms import ActivationOTPForm, IdentifierPasswordResetForm, LoginForm


def _request_limit_key(scope, request, identifier):
    """Create a cache-safe key without storing the submitted identity value."""
    remote_address = request.META.get("REMOTE_ADDR", "unknown")
    value = f"{scope}|{remote_address}|{(identifier or '').strip().casefold()}"
    return f"fmis-limit:{scope}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _record_attempt(key, timeout):
    attempts = int(cache.get(key, 0)) + 1
    cache.set(key, attempts, timeout=timeout)
    return attempts


def dashboard_for(user):
    return "dashboard:admin_home" if user.is_admin else "dashboard:staff_home"


def configure_login_session(request, remember_me):
    """Apply either a fixed remembered-login window or a browser-only session."""
    if remember_me:
        request.session.set_expiry(settings.REMEMBER_LOGIN_SECONDS)
        request.session[REMEMBER_UNTIL_SESSION_KEY] = (
            int(time.time()) + settings.REMEMBER_LOGIN_SECONDS
        )
    else:
        request.session.set_expiry(0)
        request.session.pop(REMEMBER_UNTIL_SESSION_KEY, None)


class PrivacyNoticeView(TemplateView):
    template_name = "authentication/privacy.html"


class TermsOfUseView(TemplateView):
    template_name = "authentication/terms.html"


class UserLoginView(LoginView):
    template_name = "authentication/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        self.login_limit_key = _request_limit_key(
            "login", request, request.POST.get("username", "")
        )
        if int(cache.get(self.login_limit_key, 0)) >= 5:
            self.login_is_limited = True
            form = self.get_form()
            form.add_error(
                "username", "Too many unsuccessful sign-in attempts. Wait 10 minutes and try again."
            )
            return self.form_invalid(form)
        pending_user = get_user_model().objects.filter(
            username__iexact=request.POST.get("username", "").strip(),
            is_active=False,
            activation_pending=True,
        ).first()
        if pending_user and pending_user.check_password(request.POST.get("password", "")):
            if not pending_user.email:
                form = self.get_form()
                form.add_error("username", "Ask an administrator to add an email address first.")
                return self.form_invalid(form)
            try:
                send_activation_code(
                    request,
                    pending_user,
                    remember_me=bool(request.POST.get("remember_me")),
                )
            except Exception:
                form = self.get_form()
                form.add_error(
                    "username",
                    "The activation email could not be sent. Check the email configuration and try again.",
                )
                return self.form_invalid(form)
            cache.delete(self.login_limit_key)
            messages.info(request, "A six-digit activation code was sent to the account email.")
            return redirect("authentication:activate_account")
        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        redirect_to = self.get_redirect_url()
        if redirect_to:
            return redirect_to
        return reverse_lazy(dashboard_for(self.request.user))

    def form_valid(self, form):
        if getattr(self, "login_limit_key", None):
            cache.delete(self.login_limit_key)
        response = super().form_valid(form)
        record_request_event(
            self.request,
            title="Successful sign-in",
            module="Security",
            description=f"{self.request.user.display_name} signed in successfully.",
            target_label=self.request.user.username,
        )
        configure_login_session(self.request, form.cleaned_data.get("remember_me"))
        return response

    def form_invalid(self, form):
        if getattr(self, "login_limit_key", None) and not getattr(self, "login_is_limited", False):
            _record_attempt(self.login_limit_key, timeout=10 * 60)
        if self.request.method == "POST":
            identifier = self.request.POST.get("username", "").strip()[:150]
            limited = getattr(self, "login_is_limited", False)
            record_event(
                title="Sign-in blocked" if limited else "Failed sign-in",
                module="Security",
                description=(
                    "A sign-in attempt was blocked after repeated failures."
                    if limited
                    else "A sign-in attempt did not pass authentication."
                ),
                path=self.request.path,
                status="Blocked" if limited else "Warning",
                target_label=identifier or "Unknown account",
            )
        return super().form_invalid(form)


class LandingPageView(UserLoginView):
    """Public landing page with the same secure sign-in flow as /login/."""

    template_name = "authentication/landing.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["username"].widget.attrs.pop("autofocus", None)
        return form


class UserLogoutView(LogoutView):
    next_page = reverse_lazy("authentication:landing")


class AccountActivationView(FormView):
    template_name = "authentication/account_activation.html"
    form_class = ActivationOTPForm

    def dispatch(self, request, *args, **kwargs):
        nonce, challenge = get_activation_challenge(request)
        if not nonce or not challenge:
            messages.warning(request, "The activation code expired. Sign in again to request a new code.")
            return redirect("authentication:landing")
        self.activation_nonce = nonce
        self.activation_challenge = challenge
        self.activation_user = get_user_model().objects.filter(
            pk=challenge["user_id"],
            is_active=False,
            activation_pending=True,
        ).first()
        if not self.activation_user:
            clear_activation_challenge(request, nonce)
            return redirect("authentication:landing")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["masked_email"] = masked_email(self.activation_user.email)
        context["attempts_remaining"] = max(
            0,
            ACTIVATION_MAX_ATTEMPTS - self.activation_challenge["attempts"],
        )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "resend":
            remember_me = self.activation_challenge.get("remember_me", False)
            clear_activation_challenge(request, self.activation_nonce)
            try:
                send_activation_code(request, self.activation_user, remember_me=remember_me)
            except Exception:
                messages.error(request, "The activation email could not be sent. Try again later.")
                return redirect("authentication:landing")
            messages.success(request, "A new six-digit code was sent.")
            return redirect("authentication:activate_account")
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        if not verify_activation_code(
            self.activation_nonce,
            self.activation_challenge,
            form.cleaned_data["code"],
        ):
            form.add_error("code", "That code is incorrect or has expired.")
            return self.form_invalid(form)

        remember_me = self.activation_challenge.get("remember_me", False)
        user = self.activation_user
        user.is_active = True
        user.activation_pending = False
        user.save(update_fields=["is_active", "activation_pending"])
        clear_activation_challenge(self.request, self.activation_nonce)
        login(
            self.request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        configure_login_session(self.request, remember_me)
        record_request_event(
            self.request,
            title="Account activated",
            module="Security",
            description=f"{user.display_name} completed first-time account activation.",
            target_label=user.username,
        )
        messages.success(self.request, "Your FMIS staff account is now active.")
        return redirect(reverse(dashboard_for(user)))


class PasswordRecoveryView(FormView):
    template_name = "authentication/password_reset_form.html"
    form_class = IdentifierPasswordResetForm
    success_url = reverse_lazy("authentication:password_reset_done")

    def form_valid(self, form):
        identifier = form.cleaned_data["identifier"].strip()
        recovery_limit_key = _request_limit_key("password-recovery", self.request, identifier)
        if int(cache.get(recovery_limit_key, 0)) >= 3:
            form.add_error("identifier", "Too many reset requests. Wait 15 minutes and try again.")
            return self.form_invalid(form)
        _record_attempt(recovery_limit_key, timeout=15 * 60)
        # Both email and phone identifiers send a secure reset link to the
        # account's registered email. Unknown identifiers receive the same page.
        form.save(request=self.request)
        return super().form_valid(form)
