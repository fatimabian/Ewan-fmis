from django.urls import path
from .views import AdminDashboardView, DashboardLandingView, StaffDashboardView
app_name = "dashboard"
urlpatterns = [path("", DashboardLandingView.as_view(), name="home"), path("admin/", AdminDashboardView.as_view(), name="admin_home"), path("staff/", StaffDashboardView.as_view(), name="staff_home")]
