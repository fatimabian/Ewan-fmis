from django.urls import path
from .views import (
    FarmerLocationPinView,
    FarmParcelCreateView,
    FarmParcelDeleteView,
    FarmParcelDetailView,
    FarmParcelHistoryView,
    FarmParcelListView,
    FarmParcelMapView,
    FarmParcelPhotoArchiveView,
    FarmParcelPhotoView,
    FarmParcelPhotoUploadView,
    FarmParcelUpdateView,
)

app_name = "farm_parcels"
urlpatterns = [
    path("", FarmParcelListView.as_view(), name="list"),
    path("map/", FarmParcelMapView.as_view(), name="map"),
    path("map/pin/", FarmerLocationPinView.as_view(), name="pin_farmer"),
    path("new/", FarmParcelCreateView.as_view(), name="create"),
    path("<int:pk>/", FarmParcelDetailView.as_view(), name="detail"),
    path("<int:pk>/history/", FarmParcelHistoryView.as_view(), name="history"),
    path("<int:pk>/edit/", FarmParcelUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", FarmParcelDeleteView.as_view(), name="delete"),
    path(
        "<int:pk>/photos/upload/",
        FarmParcelPhotoUploadView.as_view(),
        name="photo_upload",
    ),
    path(
        "<int:pk>/photos/<int:photo_pk>/view/",
        FarmParcelPhotoView.as_view(),
        name="photo_view",
    ),
    path(
        "<int:pk>/photos/<int:photo_pk>/remove/",
        FarmParcelPhotoArchiveView.as_view(),
        name="photo_remove",
    ),
]
