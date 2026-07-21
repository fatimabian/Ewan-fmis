from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls), path("", include("apps.authentication.urls")),
    path("dashboard/", include("apps.dashboard.urls")), path("accounts/", include("apps.accounts.urls")),
    path("farmers/", include("apps.farmers.urls")), path("parcels/", include("apps.farm_parcels.urls")),
    path("crops/", include("apps.crops.urls")), path("catalog/", include("apps.service_catalog.urls")),
    path("requests/", include("apps.service_requests.urls")), path("reports/", include("apps.reports.urls")),
    path("activity/", include("apps.activity_logs.urls")), path("settings/", include("apps.settings_page.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
