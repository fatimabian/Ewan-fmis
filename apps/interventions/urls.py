from django.urls import path

from .views import (
    InterventionArchiveView,
    InterventionCreateView,
    InterventionDetailView,
    InterventionHistoryView,
    InterventionFarmerSearchView,
    InterventionListView,
    InterventionUpdateView,
)

app_name = "interventions"
urlpatterns = [
    path("", InterventionListView.as_view(), name="list"),
    path("farmer-search/", InterventionFarmerSearchView.as_view(), name="farmer_search"),
    path("new/", InterventionCreateView.as_view(), name="create"),
    path("<int:pk>/", InterventionDetailView.as_view(), name="detail"),
    path("<int:pk>/history/", InterventionHistoryView.as_view(), name="history"),
    path("<int:pk>/edit/", InterventionUpdateView.as_view(), name="edit"),
    path("<int:pk>/archive/", InterventionArchiveView.as_view(), name="archive"),
]
