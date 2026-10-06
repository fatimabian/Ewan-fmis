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
from .forms import (
    ActivationOTPForm,
    IdentifierPasswordResetForm,
    LoginForm,
    PasswordRecoveryOTPForm,
    RecoverySetPasswordForm,
)
from .recovery import (
    RECOVERY_MAX_ATTEMPTS,
    clear_recovery_challenge,
    get_recovery_challenge,
    recovery_destination,
    start_recovery_challenge,
    verify_recovery_code,
)


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html"
            if self.request.user.is_authenticated and self.request.user.is_admin
            else "base/staff_base.html"
            if self.request.user.is_authenticated
            else "authentication/legal_base.html"
        )
        return context


class TermsOfUseView(TemplateView):
    template_name = "authentication/terms.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["base_template"] = (
            "base/admin_base.html"
            if self.request.user.is_authenticated and self.request.user.is_admin
            else "base/staff_base.html"
            if self.request.user.is_authenticated
            else "authentication/legal_base.html"
        )
        return context


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["login_form"] = context["form"]
        return context


class UserLogoutView(LogoutView):
    next_page = reverse_lazy("authentication:landing")


class AccountActivationView(FormView):
    template_name = "authentication/landing.html"
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
        context["activation_mode"] = True
        context["activation_form"] = context["form"]
        context["login_form"] = LoginForm(request=self.request)
        context["masked_email"] = masked_email(self.activation_user.email)
        context["attempts_remaining"] = max(
            0,
            ACTIVATION_MAX_ATTEMPTS - self.activation_challenge["attempts"],
        )
        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "resend":
            resend_limit_key = _request_limit_key(
                "activation-resend", request, str(self.activation_user.pk)
            )
            if int(cache.get(resend_limit_key, 0)) >= 3:
                messages.error(
                    request,
                    "Too many activation-code requests. Wait 15 minutes and try again.",
                )
                return redirect("authentication:activate_account")
            _record_attempt(resend_limit_key, timeout=15 * 60)
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


class PasswordRecoveryView(TemplateView):
    """Session-bound email OTP password recovery rendered inside the landing modal."""

    template_name = "authentication/landing.html"

    def _context(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("login_form", LoginForm(request=self.request))
        context["recovery_mode"] = True
        context.setdefault("recovery_step", "request")
        context.setdefault("recovery_identifier_form", IdentifierPasswordResetForm())
        return context

    def get(self, request, *args, **kwargs):
        clear_recovery_challenge(request)
        return self.render_to_response(self._context())

    def post(self, request, *args, **kwargs):
        action = request.POST.get("recovery_action", "request")
        if action == "cancel":
            clear_recovery_challenge(request)
            return redirect("authentication:landing")
        if action == "request":
            return self._request_code(request)
        if action == "verify":
            return self._verify_code(request)
        if action == "reset":
            return self._reset_password(request)
        clear_recovery_challenge(request)
        return redirect("authentication:landing")

    def _request_code(self, request):
        form = IdentifierPasswordResetForm(request.POST)
        if not form.is_valid():
            return self.render_to_response(
                self._context(recovery_identifier_form=form), status=400
            )
        identifier = form.cleaned_data["identifier"].strip()
        limit_key = _request_limit_key("password-recovery", request, identifier)
        if int(cache.get(limit_key, 0)) >= 3:
            form.add_error("identifier", "Too many code requests. Wait 15 minutes and try again.")
            return self.render_to_response(
                self._context(recovery_identifier_form=form), status=429
            )
        _record_attempt(limit_key, timeout=15 * 60)
        user = next((item for item in form.matching_users() if item.email), None)
        clear_recovery_challenge(request)
        try:
            start_recovery_challenge(request, user)
        except Exception:
            form.add_error("identifier", "The recovery email could not be sent. Try again later.")
            return self.render_to_response(
                self._context(recovery_identifier_form=form), status=503
            )
        return self.render_to_response(
            self._context(
                recovery_step="verify",
                recovery_otp_form=PasswordRecoveryOTPForm(),
                recovery_destination=recovery_destination(user),
                recovery_attempts=RECOVERY_MAX_ATTEMPTS,
            )
        )

    def _verify_code(self, request):
        nonce, challenge = get_recovery_challenge(request)
        if not nonce or not challenge:
            return self.render_to_response(
                self._context(recovery_error="The code expired. Request a new code."),
                status=400,
            )
        form = PasswordRecoveryOTPForm(request.POST)
        user = get_user_model().objects.filter(pk=challenge.get("user_id"), is_active=True).first()
        if form.is_valid() and verify_recovery_code(
            nonce, challenge, form.cleaned_data["code"]
        ):
            return self.render_to_response(
                self._context(
                    recovery_step="reset",
                    recovery_password_form=RecoverySetPasswordForm(user),
                )
            )
        if form.is_valid():
            form.add_error("code", "That code is incorrect or has expired.")
        _, updated = get_recovery_challenge(request)
        remaining = max(0, RECOVERY_MAX_ATTEMPTS - (updated or {}).get("attempts", 0))
        return self.render_to_response(
            self._context(
                recovery_step="verify",
                recovery_otp_form=form,
                recovery_destination=recovery_destination(user),
                recovery_attempts=remaining,
            ),
            status=400,
        )

    def _reset_password(self, request):
        nonce, challenge = get_recovery_challenge(request)
        user = get_user_model().objects.filter(
            pk=(challenge or {}).get("user_id"), is_active=True
        ).first()
        if not nonce or not challenge or not challenge.get("verified") or not user:
            clear_recovery_challenge(request, nonce)
            return self.render_to_response(
                self._context(recovery_error="Verify a new recovery code before changing the password."),
                status=400,
            )
        form = RecoverySetPasswordForm(user, request.POST)
        if not form.is_valid():
            return self.render_to_response(
                self._context(recovery_step="reset", recovery_password_form=form),
                status=400,
            )
        form.save()
        clear_recovery_challenge(request, nonce)
        request.session.cycle_key()
        cache.delete(_request_limit_key("password-recovery", request, user.email))
        record_event(
            title="Password reset completed",
            module="Security",
            description="An account password was reset after email OTP verification.",
            path=request.path,
            status="Success",
            target_label=user.username,
        )
        messages.success(request, "Your password was changed. Sign in with your new password.")
        return redirect("authentication:landing")
