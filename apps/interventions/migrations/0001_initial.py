import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("farmers", "0007_farmer_fca_membership_farmer_last_updated_at_and_more"),
        ("service_requests", "0003_servicerequesthistory"),
    ]
    operations = [
        migrations.CreateModel(
            name="Intervention",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("intervention_type", models.CharField(choices=[("SEEDS", "Seeds / planting materials"), ("FERTILIZER", "Fertilizer / soil inputs"), ("EQUIPMENT", "Equipment / machinery support"), ("TRAINING", "Training / seminar"), ("TECHNICAL", "Technical assistance"), ("FINANCIAL", "Financial assistance"), ("LIVESTOCK", "Livestock / poultry support"), ("OTHER", "Other intervention")], max_length=20)),
                ("intervention_date", models.DateField()),
                ("description", models.CharField(max_length=240)),
                ("quantity", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("unit", models.CharField(blank=True, max_length=40)),
                ("estimated_value", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("funding_source", models.CharField(blank=True, max_length=160)),
                ("provider", models.CharField(default="Office for Agricultural Services", max_length=160)),
                ("remarks", models.TextField(blank=True, max_length=1000)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("farmer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="interventions", to="farmers.farmer")),
                ("recorded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="recorded_interventions", to=settings.AUTH_USER_MODEL)),
                ("service_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="interventions", to="service_requests.servicerequest")),
            ],
            options={"ordering": ["-intervention_date", "-pk"]},
        ),
    ]
