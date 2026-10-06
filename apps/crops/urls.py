from django.urls import path

from .views import (
    CropCreateView,
    CropDeleteView,
    CropDetailView,
    FarmerCropArchiveView,
    FarmerCropDetailView,
    CropHistoryView,
    CropListView,
    CropUpdateView,
)

app_name = "crops"

urlpatterns = [
    path("", CropListView.as_view(), name="list"),
    path("new/", CropCreateView.as_view(), name="create"),
    path("farmer/<int:pk>/", FarmerCropDetailView.as_view(), name="farmer_detail"),
    path(
        "farmer/<int:pk>/records/archive/",
        FarmerCropArchiveView.as_view(),
        name="farmer_archive",
    ),
    path("<int:pk>/", CropDetailView.as_view(), name="detail"),
    path("<int:pk>/history/", CropHistoryView.as_view(), name="history"),
    path("<int:pk>/edit/", CropUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", CropDeleteView.as_view(), name="delete"),
]
