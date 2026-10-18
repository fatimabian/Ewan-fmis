import hashlib
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page, never_cache
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
    MFASetupForm,
    MFAVerificationForm,
    PasswordRecoveryOTPForm,
    RecoverySetPasswordForm,
)
from .mfa import (
    MFA_MAX_ATTEMPTS,
    MFA_RECOVERY_SESSION_KEY,
    clear_mfa_challenge,
    consume_recovery_code,
    decrypt_secret,
    encrypt_secret,
    generate_recovery_codes,
    generate_secret,
    get_mfa_challenge,
    hash_recovery_codes,
    forget_trusted_devices,
    provisioning_qr_data_uri,
    remember_trusted_device,
    start_mfa_challenge,
    trusted_device_is_valid,
    verify_totp,
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


def _mfa_destination(request, challenge, user):
    candidate = challenge.get("next_url", "")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse(dashboard_for(user))


def _complete_mfa_login(request, user, challenge, *, method):
    destination = _mfa_destination(request, challenge, user)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    configure_login_session(request, challenge.get("remember_me", False))
    clear_mfa_challenge(request)
    record_request_event(
        request,
        title="Successful sign-in",
        module="Security",
        description=f"{user.display_name} completed a protected sign-in.",
        target_label=user.username,
        details=[{"field": "Second factor", "after": method}],
    )
    return destination


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["remember_login_seconds"] = settings.REMEMBER_LOGIN_SECONDS
        return context

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
        user = form.get_user()
        if settings.FMIS_REQUIRE_MFA:
            start_mfa_challenge(
                self.request,
                user,
                remember_me=form.cleaned_data.get("remember_me"),
                next_url=self.get_redirect_url(),
            )
            if user.mfa_enabled and trusted_device_is_valid(self.request, user):
                destination = _complete_mfa_login(
                    self.request,
                    user,
                    get_mfa_challenge(self.request),
                    method="Trusted browser",
                )
                return redirect(destination)
            return redirect(
                "authentication:mfa_verify"
                if user.mfa_enabled
                else "authentication:mfa_setup"
            )
        response = super().form_valid(form)
        configure_login_session(self.request, form.cleaned_data.get("remember_me"))
        record_request_event(
            self.request,
            title="Successful sign-in",
            module="Security",
            description=f"{user.display_name} signed in successfully.",
            target_label=user.username,
        )
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


@method_decorator(cache_page(settings.PUBLIC_PAGE_CACHE_SECONDS), name="dispatch")
class LandingPageView(TemplateView):
    """Public information page; authentication lives on dedicated pages."""
    template_name = "authentication/landing.html"


class UserLogoutView(LogoutView):
    next_page = reverse_lazy("authentication:landing")

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        forget_trusted_devices(response)
        return response


class AccountActivationView(FormView):
    template_name = "authentication/activate_account.html"
    form_class = ActivationOTPForm

    def dispatch(self, request, *args, **kwargs):
        nonce, challenge = get_activation_challenge(request)
        if not nonce or not challenge:
            messages.warning(request, "The activation code expired. Sign in again to request a new code.")
            return redirect("authentication:login")
        self.activation_nonce = nonce
        self.activation_challenge = challenge
        self.activation_user = get_user_model().objects.filter(
            pk=challenge["user_id"],
            is_active=False,
            activation_pending=True,
        ).first()
        if not self.activation_user:
            clear_activation_challenge(request, nonce)
            return redirect("authentication:login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["activation_form"] = context["form"]
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
                return redirect("authentication:login")
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
        if settings.FMIS_REQUIRE_MFA:
            start_mfa_challenge(self.request, user, remember_me=remember_me)
            record_event(
                title="Account activated",
                module="Security",
                description=f"{user.display_name} completed first-time email activation.",
                path=self.request.path,
                status="Success",
                target_label=user.username,
            )
            messages.success(
                self.request,
                "Your email is verified. Set up your authenticator app to finish securing the account.",
            )
            return redirect("authentication:mfa_setup")
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


class PendingMFAViewMixin:
    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        if not settings.FMIS_REQUIRE_MFA:
            clear_mfa_challenge(request)
            return redirect("authentication:login")
        if request.user.is_authenticated:
            return redirect(dashboard_for(request.user))
        self.mfa_challenge = get_mfa_challenge(request)
        if not self.mfa_challenge:
            messages.warning(request, "The sign-in verification expired. Enter your password again.")
            return redirect("authentication:login")
        self.mfa_user = get_user_model().objects.filter(
            pk=self.mfa_challenge.get("user_id"),
            is_active=True,
            deleted_at__isnull=True,
        ).first()
        if not self.mfa_user:
            clear_mfa_challenge(request)
            return redirect("authentication:login")
        return super().dispatch(request, *args, **kwargs)


class MFASetupView(PendingMFAViewMixin, FormView):
    template_name = "authentication/mfa_setup.html"
    form_class = MFASetupForm

    def get(self, request, *args, **kwargs):
        if self.mfa_user.mfa_enabled:
            return redirect("authentication:mfa_verify")
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.mfa_user.mfa_enabled:
            return redirect("authentication:mfa_verify")
        return super().post(request, *args, **kwargs)

    def _secret(self):
        secret = self.request.session.get("fmis_mfa_setup_secret")
        if not secret:
            secret = generate_secret()
            self.request.session["fmis_mfa_setup_secret"] = secret
        return secret

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        secret = self._secret()
        context.update(
            mfa_form=context["form"],
            qr_data_uri=provisioning_qr_data_uri(secret, self.mfa_user),
            manual_key=secret,
            account_label=self.mfa_user.email or self.mfa_user.username,
            attempts_remaining=max(
                0,
                MFA_MAX_ATTEMPTS
                - int(
                    cache.get(
                        _request_limit_key("mfa-setup", self.request, str(self.mfa_user.pk)),
                        0,
                    )
                ),
            ),
        )
        return context

    def form_valid(self, form):
        limit_key = _request_limit_key("mfa-setup", self.request, str(self.mfa_user.pk))
        if int(cache.get(limit_key, 0)) >= MFA_MAX_ATTEMPTS:
            form.add_error("code", "Too many incorrect codes. Wait 10 minutes and sign in again.")
            clear_mfa_challenge(self.request)
            return self.form_invalid(form)
        secret = self._secret()
        counter = verify_totp(secret, form.cleaned_data["code"])
        if counter is None:
            attempts = _record_attempt(limit_key, timeout=10 * 60)
            form.add_error(
                "code",
                "That code is incorrect. Check the phone time and try again."
                if attempts < MFA_MAX_ATTEMPTS
                else "Too many incorrect codes. Wait 10 minutes and sign in again.",
            )
            if attempts >= MFA_MAX_ATTEMPTS:
                clear_mfa_challenge(self.request)
            return self.form_invalid(form)
        cache.delete(limit_key)
        recovery_codes = generate_recovery_codes()
        user = self.mfa_user
        user.mfa_enabled = True
        user.mfa_secret = encrypt_secret(secret)
        user.mfa_recovery_codes = hash_recovery_codes(recovery_codes)
        user.mfa_last_counter = counter
        user.mfa_version += 1
        user.save(
            update_fields=[
                "mfa_enabled",
                "mfa_secret",
                "mfa_recovery_codes",
                "mfa_last_counter",
                "mfa_version",
            ]
        )
        destination = _complete_mfa_login(
            self.request, user, self.mfa_challenge, method="Authenticator app enrollment"
        )
        self.request.session[MFA_RECOVERY_SESSION_KEY] = recovery_codes
        self.request.session["fmis_mfa_destination"] = destination
        messages.success(self.request, "Authenticator verification is now enabled.")
        response = redirect("authentication:mfa_recovery_codes")
        if form.cleaned_data.get("trust_device"):
            remember_trusted_device(self.request, response, user)
        else:
            forget_trusted_devices(response)
        return response


class MFAVerificationView(PendingMFAViewMixin, FormView):
    template_name = "authentication/mfa_verify.html"
    form_class = MFAVerificationForm

    def get(self, request, *args, **kwargs):
        if not self.mfa_user.mfa_enabled:
            return redirect("authentication:mfa_setup")
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if not self.mfa_user.mfa_enabled:
            return redirect("authentication:mfa_setup")
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["mfa_form"] = context["form"]
        context["attempts_remaining"] = max(
            0,
            MFA_MAX_ATTEMPTS
            - int(cache.get(_request_limit_key("mfa", self.request, str(self.mfa_user.pk)), 0)),
        )
        return context

    def form_valid(self, form):
        limit_key = _request_limit_key("mfa", self.request, str(self.mfa_user.pk))
        if int(cache.get(limit_key, 0)) >= MFA_MAX_ATTEMPTS:
            form.add_error("code", "Too many incorrect codes. Wait 10 minutes and sign in again.")
            clear_mfa_challenge(self.request)
            return self.form_invalid(form)

        submitted = form.cleaned_data["code"]
        with transaction.atomic():
            locked_user = get_user_model().objects.select_for_update().get(pk=self.mfa_user.pk)
            secret = decrypt_secret(locked_user.mfa_secret)
            counter = (
                verify_totp(
                    secret,
                    submitted,
                    last_counter=locked_user.mfa_last_counter,
                )
                if secret
                else None
            )
            method = None
            if counter is not None:
                locked_user.mfa_last_counter = counter
                locked_user.save(update_fields=["mfa_last_counter"])
                method = "Authenticator app"
            elif consume_recovery_code(locked_user, submitted):
                method = "Recovery code"
            self.mfa_user = locked_user

        if not method:
            attempts = _record_attempt(limit_key, timeout=10 * 60)
            form.add_error(
                "code",
                "That code is invalid, expired, or already used."
                if attempts < MFA_MAX_ATTEMPTS
                else "Too many incorrect codes. Wait 10 minutes and sign in again.",
            )
            if attempts >= MFA_MAX_ATTEMPTS:
                clear_mfa_challenge(self.request)
            return self.form_invalid(form)

        cache.delete(limit_key)
        destination = _complete_mfa_login(
            self.request, self.mfa_user, self.mfa_challenge, method=method
        )
        response = redirect(destination)
        if form.cleaned_data.get("trust_device"):
            remember_trusted_device(self.request, response, self.mfa_user)
        else:
            forget_trusted_devices(response)
        return response


class MFARecoveryCodesView(TemplateView):
    template_name = "authentication/mfa_recovery_codes.html"

    @method_decorator(never_cache)
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("authentication:login")
        if not request.session.get(MFA_RECOVERY_SESSION_KEY):
            return redirect(dashboard_for(request.user))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["recovery_codes"] = self.request.session[MFA_RECOVERY_SESSION_KEY]
        return context

    def post(self, request, *args, **kwargs):
        destination = request.session.pop(
            "fmis_mfa_destination", reverse(dashboard_for(request.user))
        )
        request.session.pop(MFA_RECOVERY_SESSION_KEY, None)
        return redirect(destination)


class PasswordRecoveryView(TemplateView):
    """Session-bound email OTP password recovery on a dedicated public page."""

    template_name = "authentication/password_recovery.html"

    def _context(self, **kwargs):
        context = super().get_context_data(**kwargs)
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
            return redirect("authentication:login")
        if action == "request":
            return self._request_code(request)
        if action == "verify":
            return self._verify_code(request)
        if action == "reset":
            return self._reset_password(request)
        clear_recovery_challenge(request)
        return redirect("authentication:login")

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

        # Repeated submits from the same browser must keep using the active
        # challenge. This prevents impatient taps or a retried POST from
        # generating several valid codes and several email messages.
        _nonce, active_challenge = get_recovery_challenge(request)
        if active_challenge and active_challenge.get("user_id") == (
            user.pk if user else None
        ):
            return self.render_to_response(
                self._context(
                    recovery_step="verify",
                    recovery_otp_form=PasswordRecoveryOTPForm(),
                    recovery_destination=recovery_destination(user),
                    recovery_attempts=max(
                        0,
                        RECOVERY_MAX_ATTEMPTS
                        - int(active_challenge.get("attempts", 0)),
                    ),
                )
            )

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
        changed_user = form.save()
        changed_user.mfa_version += 1
        changed_user.save(update_fields=["mfa_version"])
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
        return redirect("authentication:login")
