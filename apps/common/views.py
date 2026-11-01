from django.contrib import messages
from django.contrib.auth import logout
from django.db import DatabaseError, connection
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST


@never_cache
@require_GET
def health_check(request):
    """Minimal external readiness probe without operational or personal data."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable"}, status=503)
    response = JsonResponse({"status": "ok"})
    response["Cache-Control"] = "no-store"
    return response


@never_cache
@require_POST
def expire_idle_session(request):
    """End an idle browser session when the page-side inactivity timer fires."""
    if request.user.is_authenticated:
        logout(request)
        messages.warning(
            request,
            "Your session expired due to inactivity. Please sign in again.",
        )
    response = JsonResponse({"login_url": reverse("authentication:login")})
    response["Cache-Control"] = "no-store"
    return response


@never_cache
@require_POST
def record_session_activity(request):
    """Cheap endpoint used only to persist recent, genuine browser activity."""
    response = HttpResponse(status=204 if request.user.is_authenticated else 401)
    response["Cache-Control"] = "no-store"
    return response
