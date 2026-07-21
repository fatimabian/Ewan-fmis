from django.urls import path
from .views import ChangePasswordView, ManualBackupView, SettingsView
app_name = "settings_page"
urlpatterns = [
    path("", SettingsView.as_view(), name="home"),
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("backup/manual/", ManualBackupView.as_view(), name="manual_backup"),
]
