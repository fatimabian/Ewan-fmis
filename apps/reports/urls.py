from django.urls import path
from .views import FarmerExportView, ReportsView
app_name = "reports"
urlpatterns = [path("", ReportsView.as_view(), name="home"), path("farmers.csv", FarmerExportView.as_view(), name="farmers_csv")]
