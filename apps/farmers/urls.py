from django.urls import path

from .views import (
    FarmerDeleteView,
    FarmerDetailView,
    FarmerListView,
    FarmerQRPrintView,
    FarmerRegistrationCompleteView,
    FarmerRegistrationView,
    FarmerSecureQRDetailView,
    FarmerUpdateView,
)

app_name = "farmers"

urlpatterns = [
    path("", FarmerListView.as_view(), name="list"),
    path("new/", FarmerRegistrationView.as_view(), name="create"),
    path("field/<str:token>/", FarmerSecureQRDetailView.as_view(), name="qr_access"),
    path("<int:pk>/qr/", FarmerQRPrintView.as_view(), name="qr_print"),
    path("<int:pk>/", FarmerDetailView.as_view(), name="detail"),
    path("<int:pk>/registration-complete/", FarmerRegistrationCompleteView.as_view(), name="registration_complete"),
    path("<int:pk>/edit/", FarmerUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", FarmerDeleteView.as_view(), name="delete"),
]
