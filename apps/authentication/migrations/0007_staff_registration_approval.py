from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0006_customuser_mfa"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="approval_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending administrator approval"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                ],
                db_index=True,
                default="APPROVED",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="customuser",
            name="approval_reviewed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="approval_reviewed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reviewed_staff_registrations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
