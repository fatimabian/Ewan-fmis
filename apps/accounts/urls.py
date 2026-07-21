from django.urls import path
from .views import AccountCreateView, AccountDeleteView, AccountDetailView, AccountListView, AccountUpdateView
app_name = "accounts"
urlpatterns = [
    path("", AccountListView.as_view(), name="list"),
    path("new/", AccountCreateView.as_view(), name="create"),
    path("<int:pk>/", AccountDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", AccountUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", AccountDeleteView.as_view(), name="delete"),
]
