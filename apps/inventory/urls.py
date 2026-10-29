from django.urls import path

from .views import (
    InventoryItemArchiveView,
    InventoryItemCreateView,
    InventoryItemDetailView,
    InventoryItemUpdateView,
    InventoryListView,
    InventoryMovementCreateView,
)

app_name = "inventory"

urlpatterns = [
    path("", InventoryListView.as_view(), name="list"),
    path("items/new/", InventoryItemCreateView.as_view(), name="item_create"),
    path("items/<int:pk>/", InventoryItemDetailView.as_view(), name="detail"),
    path("items/<int:pk>/edit/", InventoryItemUpdateView.as_view(), name="item_edit"),
    path("items/<int:pk>/archive/", InventoryItemArchiveView.as_view(), name="item_archive"),
    path("movements/new/", InventoryMovementCreateView.as_view(), name="movement_create"),
]
