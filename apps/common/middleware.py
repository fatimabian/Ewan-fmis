import time
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import logout
from django.core.cache import cache
from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import patch_cache_control, patch_vary_headers


REMEMBER_UNTIL_SESSION_KEY = "fmis_remember_until"


class SessionTimeoutMiddleware:
    """End authenticated sessions after the administrator's idle-time limit."""

    CACHE_KEY = "fmis:session-timeout-minutes"
    SESSION_KEY = "fmis_last_activity"
    DEFAULT_MINUTES = 15

    def __init__(self, get_response):
        self.get_response = get_response

    def _timeout_seconds(self):
        timeout = cache.get(self.CACHE_KEY)
        if timeout is not None:
            return int(timeout) * 60
        try:
            from apps.settings_page.models import SystemSetting

            timeout = max(1, int(SystemSetting.load().session_timeout))
        except (DatabaseError, ValueError, TypeError):
            timeout = self.DEFAULT_MINUTES
        cache.set(self.CACHE_KEY, timeout, 60)
        return timeout * 60

    def __call__(self, request):
        if request.user.is_authenticated:
            now = int(time.time())
            remember_until = request.session.get(REMEMBER_UNTIL_SESSION_KEY)
            if remember_until:
                try:
                    remembered_session_expired = now >= int(remember_until)
                except (TypeError, ValueError):
                    remembered_session_expired = True
                if remembered_session_expired:
                    logout(request)
                    if request.headers.get("x-requested-with") == "XMLHttpRequest":
                        return JsonResponse(
                            {"detail": "Your seven-day remembered sign-in has expired."},
                            status=401,
                        )
                    messages.info(
                        request,
                        "For your security, please sign in again after seven days.",
                    )
                    landing_url = reverse("authentication:landing")
                    return redirect(
                        f"{landing_url}?{urlencode({'next': request.get_full_path()})}"
                    )
                # A remembered device uses the fixed seven-day limit instead
                # of the much shorter ordinary idle timeout.
                request.session[self.SESSION_KEY] = now
                return self.get_response(request)
            last_activity = request.session.get(self.SESSION_KEY)
            if last_activity and now - int(last_activity) > self._timeout_seconds():
                logout(request)
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse(
                        {"detail": "Your session expired due to inactivity."}, status=401
                    )
                messages.warning(
                    request, "Your session expired due to inactivity. Please sign in again."
                )
                landing_url = reverse("authentication:landing")
                return redirect(
                    f"{landing_url}?{urlencode({'next': request.get_full_path()})}"
                )
            request.session[self.SESSION_KEY] = now
        return self.get_response(request)


class PrivateUserPageMiddleware:
    """Prevent one signed-in user's rendered preferences appearing for another."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            patch_cache_control(response, private=True, no_store=True)
            patch_vary_headers(response, ("Cookie",))
        return response


class SecurityHeadersMiddleware:
    """Apply a conservative browser security policy to every FMIS response."""

    CONTENT_SECURITY_POLICY = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "img-src 'self' data: blob: https://server.arcgisonline.com; "
        "connect-src 'self' https://api.open-meteo.com"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CONTENT_SECURITY_POLICY)
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response
