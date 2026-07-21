from django.urls import path
from .views import CatalogCreateView, CatalogDeleteView, CatalogListView, CatalogUpdateView
app_name = "service_catalog"
urlpatterns = [path("", CatalogListView.as_view(), name="list"), path("new/", CatalogCreateView.as_view(), name="create"), path("<int:pk>/edit/", CatalogUpdateView.as_view(), name="edit"), path("<int:pk>/delete/", CatalogDeleteView.as_view(), name="delete")]
