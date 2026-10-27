from django.urls import path
from .views import (
    FarmerLocationPinView,
    FarmParcelCreateView,
    FarmParcelDeleteView,
    FarmParcelDetailView,
    FarmParcelHistoryView,
    FarmParcelListView,
    FarmParcelMapView,
    FarmParcelMapDataView,
    FarmParcelMapDetailView,
    FarmParcelMapParcelListView,
    FarmParcelMapSearchView,
    FarmParcelPhotoArchiveView,
    FarmParcelPhotoView,
    FarmParcelPhotoUploadView,
    FarmParcelUpdateView,
    CoordinateVerificationListView,
    CoordinateReviewApproveView,
    CoordinateReviewRejectView,
    CoordinateHistoryReverseView,
)

app_name = "farm_parcels"
urlpatterns = [
    path("", FarmParcelListView.as_view(), name="list"),
    path("map/", FarmParcelMapView.as_view(), name="map"),
    path("map/data/", FarmParcelMapDataView.as_view(), name="map_data"),
    path("map/data/<int:pk>/", FarmParcelMapDetailView.as_view(), name="map_detail"),
    path("map/parcels/", FarmParcelMapParcelListView.as_view(), name="map_parcels"),
    path("map/search/", FarmParcelMapSearchView.as_view(), name="map_search"),
    path("map/pin/", FarmerLocationPinView.as_view(), name="pin_farmer"),
    path(
        "map/verification/",
        CoordinateVerificationListView.as_view(),
        name="coordinate_verification",
    ),
    path(
        "map/verification/<int:pk>/approve/",
        CoordinateReviewApproveView.as_view(),
        name="coordinate_review_approve",
    ),
    path(
        "map/verification/<int:pk>/reject/",
        CoordinateReviewRejectView.as_view(),
        name="coordinate_review_reject",
    ),
    path(
        "map/verification/history/<int:pk>/reverse/",
        CoordinateHistoryReverseView.as_view(),
        name="coordinate_history_reverse",
    ),
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
