from django.db import migrations, models


def normalize_legacy_completed_records(apps, schema_editor):
    Farmer = apps.get_model("farmers", "Farmer")
    Farmer.objects.filter(
        registration_status="COMPLETED",
        rsbsa_number__isnull=True,
    ).update(registration_status="ENCODED")
    Farmer.objects.filter(
        registration_status="COMPLETED",
        rsbsa_number="",
    ).update(registration_status="ENCODED", rsbsa_number=None)


class Migration(migrations.Migration):
    dependencies = [("farmers", "0008_farmer_registration_workflow")]

    operations = [
        migrations.RunPython(normalize_legacy_completed_records, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="farmer",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(registration_status="COMPLETED")
                    & models.Q(rsbsa_number__isnull=False)
                    & ~models.Q(rsbsa_number="")
                )
                | (
                    ~models.Q(registration_status="COMPLETED")
                    & (models.Q(rsbsa_number__isnull=True) | models.Q(rsbsa_number=""))
                ),
                name="farmer_rsbsa_id_matches_completed_status",
            ),
        ),
    ]
