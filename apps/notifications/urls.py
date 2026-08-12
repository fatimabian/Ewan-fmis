from django.urls import path

from .views import NotificationListView, NotificationMarkAllView, NotificationOpenView


app_name = "notifications"

urlpatterns = [
    path("", NotificationListView.as_view(), name="list"),
    path("<int:pk>/open/", NotificationOpenView.as_view(), name="open"),
    path("mark-all-read/", NotificationMarkAllView.as_view(), name="mark_all"),
]
