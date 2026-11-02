from django.urls import path

from .views import GISDataView, GISDetailView, GISMapView

app_name = "gis"

urlpatterns = [
    path("", GISMapView.as_view(), name="map"),
    path("data/", GISDataView.as_view(), name="data"),
    path("detail/", GISDetailView.as_view(), name="detail"),
]
