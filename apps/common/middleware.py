import time

from django.contrib import messages
from django.contrib.auth import logout
from django.core.cache import cache
from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import patch_cache_control, patch_vary_headers


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
            last_activity = request.session.get(self.SESSION_KEY)
            if last_activity and now - int(last_activity) > self._timeout_seconds():
                logout(request)
                if request.headers.get("x-requested-with") == "XMLHttpRequest":
                    return JsonResponse({"detail": "Your session expired due to inactivity."}, status=401)
                messages.warning(request, "Your session expired due to inactivity. Please sign in again.")
                return redirect(f"{reverse('authentication:login')}?next={request.path}")
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
