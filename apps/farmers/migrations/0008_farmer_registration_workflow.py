from django.db import migrations, models


FORWARD_STATUS_MAP = {
    "PENDING": "SUBMITTED",
    "APPROVED": "COMPLETED",
    "REJECTED": "SKIPPED",
}
REVERSE_STATUS_MAP = {value: key for key, value in FORWARD_STATUS_MAP.items()}


def map_statuses(apps, mapping):
    Farmer = apps.get_model("farmers", "Farmer")
    for old_status, new_status in mapping.items():
        Farmer.objects.filter(registration_status=old_status).update(
            registration_status=new_status
        )


def forwards(apps, schema_editor):
    map_statuses(apps, FORWARD_STATUS_MAP)


def backwards(apps, schema_editor):
    map_statuses(apps, REVERSE_STATUS_MAP)


class Migration(migrations.Migration):
    dependencies = [("farmers", "0007_farmer_fca_membership_farmer_last_updated_at_and_more")]

    operations = [
        migrations.AlterField(
            model_name="farmer",
            name="registration_status",
            field=models.CharField(
                choices=[
                    ("ENCODED", "Encoded"),
                    ("SUBMITTED", "Submitted"),
                    ("SKIPPED", "Skipped"),
                    ("COMPLETED", "Completed"),
                ],
                default="ENCODED",
                max_length=12,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
