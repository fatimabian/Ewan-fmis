from django.db import migrations


def approve_existing_records(apps, schema_editor):
    Farmer = apps.get_model("farmers", "Farmer")
    Farmer.objects.filter(registration_status="PENDING").update(registration_status="APPROVED")


class Migration(migrations.Migration):
    dependencies = [("farmers", "0003_farmer_location_coordinates")]

    operations = [migrations.RunPython(approve_existing_records, migrations.RunPython.noop)]
