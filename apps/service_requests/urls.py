from django.urls import path

from .views import (
    ServiceRequestCreateView,
    ServiceRequestDeleteView,
    ServiceRequestDetailView,
    ServiceRequestHistoryView,
    ServiceRequestListView,
    ServiceRequestUpdateView,
)

app_name = "service_requests"

urlpatterns = [
    path("", ServiceRequestListView.as_view(), name="list"),
    path("new/", ServiceRequestCreateView.as_view(), name="create"),
    path("<int:pk>/", ServiceRequestDetailView.as_view(), name="detail"),
    path("<int:pk>/history/", ServiceRequestHistoryView.as_view(), name="history"),
    path("<int:pk>/edit/", ServiceRequestUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", ServiceRequestDeleteView.as_view(), name="delete"),
]
