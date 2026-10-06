from django.conf import settings
from django.conf.urls.static import static
from django.http import Http404
from django.urls import include, path


def deny_direct_farmer_document_access(request, path):
    """Keep sensitive documents behind the authenticated download view in development."""
    raise Http404

urlpatterns = [
    path("", include("apps.authentication.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("farmers/", include("apps.farmers.urls")),
    path("parcels/", include("apps.farm_parcels.urls")),
    path("crops/", include("apps.crops.urls")),
    path("requests/", include("apps.service_requests.urls")),
    path("interventions/", include("apps.interventions.urls")),
    path("reports/", include("apps.reports.urls")),
    path("activity/", include("apps.activity_logs.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("settings/", include("apps.settings_page.urls")),
]
if settings.DEBUG:
    urlpatterns += [
        path(
            f"{settings.MEDIA_URL.strip('/')}/farm_documents/<path:path>",
            deny_direct_farmer_document_access,
        ),
        path(
            f"{settings.MEDIA_URL.strip('/')}/farmer_photos/<path:path>",
            deny_direct_farmer_document_access,
        ),
        path(
            f"{settings.MEDIA_URL.strip('/')}/parcel_photos/<path:path>",
            deny_direct_farmer_document_access,
        ),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
