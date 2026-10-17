from django.urls import path
from .views import ChangePasswordView, ManualBackupView, ProfilePhotoView, SettingsView

app_name = "settings_page"
urlpatterns = [
    path("", SettingsView.as_view(), name="home"),
    path("change-password/", ChangePasswordView.as_view(), name="change_password"),
    path("profile-photo/", ProfilePhotoView.as_view(), name="profile_photo"),
    path("backup/manual/", ManualBackupView.as_view(), name="manual_backup"),
]
