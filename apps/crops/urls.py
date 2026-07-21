from django.urls import path

from .views import CropCreateView, CropDeleteView, CropDetailView, CropListView, CropUpdateView

app_name = "crops"

urlpatterns = [
    path("", CropListView.as_view(), name="list"),
    path("new/", CropCreateView.as_view(), name="create"),
    path("<int:pk>/", CropDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", CropUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", CropDeleteView.as_view(), name="delete"),
]
