from django.urls import path

from .views import (
    CoverageCreateView,
    CoverageUpdateView,
    RuleCreateView,
    RuleUpdateView,
    WeatherEventDetailView,
    WeatherEventListView,
    WeatherEventReviewView,
    WeatherSettingsView,
)

app_name = "weather_monitoring"

urlpatterns = [
    path("", WeatherEventListView.as_view(), name="event_list"),
    path("settings/", WeatherSettingsView.as_view(), name="settings"),
    path("settings/areas/new/", CoverageCreateView.as_view(), name="area_create"),
    path("settings/areas/<int:pk>/", CoverageUpdateView.as_view(), name="area_edit"),
    path("settings/rules/new/", RuleCreateView.as_view(), name="rule_create"),
    path("settings/rules/<int:pk>/", RuleUpdateView.as_view(), name="rule_edit"),
    path("<int:pk>/", WeatherEventDetailView.as_view(), name="event_detail"),
    path("<int:pk>/review/", WeatherEventReviewView.as_view(), name="event_review"),
]
