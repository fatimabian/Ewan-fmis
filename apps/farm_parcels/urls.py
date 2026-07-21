from django.urls import path
from .views import FarmerLocationPinView, FarmParcelCreateView, FarmParcelDeleteView, FarmParcelDetailView, FarmParcelListView, FarmParcelMapView, FarmParcelUpdateView
app_name = "farm_parcels"
urlpatterns = [path("", FarmParcelListView.as_view(), name="list"), path("map/", FarmParcelMapView.as_view(), name="map"), path("map/pin/", FarmerLocationPinView.as_view(), name="pin_farmer"), path("new/", FarmParcelCreateView.as_view(), name="create"), path("<int:pk>/", FarmParcelDetailView.as_view(), name="detail"), path("<int:pk>/edit/", FarmParcelUpdateView.as_view(), name="edit"), path("<int:pk>/delete/", FarmParcelDeleteView.as_view(), name="delete")]
