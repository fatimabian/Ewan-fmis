from django.urls import path

from .views import ScanDiscardView, ScanImageView, ScanReviewView, ScanUploadView

app_name = "form_scan"

urlpatterns = [
    path("", ScanUploadView.as_view(), name="upload"),
    path("<int:pk>/", ScanReviewView.as_view(), name="review"),
    path("<int:pk>/discard/", ScanDiscardView.as_view(), name="discard"),
    path("<int:pk>/image/", ScanImageView.as_view(), name="image"),
    path("<int:pk>/image/<int:page>/", ScanImageView.as_view(), name="page"),
]
