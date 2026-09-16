from django.urls import path

from .views import (
    InterventionArchiveView,
    InterventionCreateView,
    InterventionDetailView,
    InterventionHistoryView,
    InterventionListView,
    InterventionUpdateView,
)

app_name = "interventions"
urlpatterns = [
    path("", InterventionListView.as_view(), name="list"),
    path("new/", InterventionCreateView.as_view(), name="create"),
    path("<int:pk>/", InterventionDetailView.as_view(), name="detail"),
    path("<int:pk>/history/", InterventionHistoryView.as_view(), name="history"),
    path("<int:pk>/edit/", InterventionUpdateView.as_view(), name="edit"),
    path("<int:pk>/archive/", InterventionArchiveView.as_view(), name="archive"),
]
