import hashlib
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["google_client_id"] = settings.GOOGLE_OAUTH_CLIENT_ID
        google_login_uri = self.request.build_absolute_uri(reverse("authentication:google_login"))
        next_url = self.get_redirect_url()
        if next_url:
            from urllib.parse import urlencode

            google_login_uri += "?" + urlencode({"next": next_url})
        context["google_login_uri"] = google_login_uri
        return context

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


@method_decorator(csrf_exempt, name="dispatch")
class GoogleLoginView(View):
    """Receive and verify a Google Identity Services ID token."""

    def post(self, request):
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            messages.error(request, "Google Sign-In is not configured yet. Add the Google OAuth client ID in the system environment.")
            return redirect("authentication:login")

        cookie_token = request.COOKIES.get("g_csrf_token", "")
        body_token = request.POST.get("g_csrf_token", "")
        if not cookie_token or not body_token or not secrets.compare_digest(cookie_token, body_token):
            messages.error(request, "Google Sign-In could not be verified. Please try again.")
            return redirect("authentication:login")

        try:
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token

            claims = id_token.verify_oauth2_token(
                request.POST.get("credential", ""),
                google_requests.Request(),
                settings.GOOGLE_OAUTH_CLIENT_ID,
            )
        except ImportError:
            messages.error(request, "Google Sign-In support is not installed. Run pip install -r requirements.txt.")
            return redirect("authentication:login")
        except ValueError:
            messages.error(request, "Google rejected or expired the sign-in request. Please try again.")
            return redirect("authentication:login")

        email = claims.get("email", "").strip()
        subject = claims.get("sub", "").strip()
        if not email or not subject or not claims.get("email_verified"):
            messages.error(request, "The selected Google account does not have a verified email address.")
            return redirect("authentication:login")

        User = get_user_model()
        user = User.objects.filter(google_sub=subject).first()
        if user is None:
            user = User.objects.filter(email__iexact=email).first()
            if user and user.google_sub and user.google_sub != subject:
                user = None
        if user is None:
            messages.error(request, "No active FMIS account matches that Google email. Ask an administrator to add the email to your user account.")
            return redirect("authentication:login")
        if not user.is_active:
            messages.error(request, "This FMIS account is inactive. Contact an administrator.")
            return redirect("authentication:login")

        if not user.google_sub:
            user.google_sub = subject
            user.save(update_fields=["google_sub"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        next_url = request.GET.get("next", "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return redirect(next_url)
        return redirect(dashboard_for(user))


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
