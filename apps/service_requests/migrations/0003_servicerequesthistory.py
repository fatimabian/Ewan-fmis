from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("service_requests", "0002_service_request_subject_priority"),
    ]

    operations = [
        migrations.CreateModel(
            name="ServiceRequestHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("CREATED", "Created"), ("UPDATED", "Updated"), ("CANCELLED", "Cancelled"), ("REOPENED", "Reopened")], max_length=20)),
                ("from_status", models.CharField(blank=True, max_length=20)),
                ("to_status", models.CharField(blank=True, max_length=20)),
                ("changes", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="service_request_updates", to=settings.AUTH_USER_MODEL)),
                ("service_request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="history", to="service_requests.servicerequest")),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
    ]
