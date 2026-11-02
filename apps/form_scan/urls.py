from django.urls import path

from .views import ScanImageView, ScanReviewView, ScanUploadView

app_name = "form_scan"

urlpatterns = [
    path("", ScanUploadView.as_view(), name="upload"),
    path("<int:pk>/", ScanReviewView.as_view(), name="review"),
    path("<int:pk>/image/", ScanImageView.as_view(), name="image"),
]
