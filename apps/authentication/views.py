import hashlib

from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, TemplateView

from .forms import IdentifierPasswordResetForm, LoginForm


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


class LandingPageView(TemplateView):
    template_name = "authentication/landing.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(dashboard_for(request.user))
        return super().dispatch(request, *args, **kwargs)


class PrivacyNoticeView(TemplateView):
    template_name = "authentication/privacy.html"


class TermsOfUseView(TemplateView):
    template_name = "authentication/terms.html"


class UserLoginView(LoginView):
    template_name = "authentication/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        self.login_limit_key = _request_limit_key("login", request, request.POST.get("username", ""))
        if int(cache.get(self.login_limit_key, 0)) >= 5:
            self.login_is_limited = True
            form = self.get_form()
            form.add_error("username", "Too many unsuccessful sign-in attempts. Wait 10 minutes and try again.")
            return self.form_invalid(form)
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
        if form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(30 * 24 * 60 * 60)
        else:
            self.request.session.set_expiry(0)
        return response

    def form_invalid(self, form):
        if getattr(self, "login_limit_key", None) and not getattr(self, "login_is_limited", False):
            _record_attempt(self.login_limit_key, timeout=10 * 60)
        return super().form_invalid(form)


class UserLogoutView(LogoutView):
    next_page = reverse_lazy("authentication:landing")


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