from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farmers", "0002_rsbsa_registration_fields")]

    operations = [
        migrations.AddField(
            model_name="farmer",
            name="location_coordinates",
            field=models.CharField(
                blank=True,
                help_text="Home location as latitude, longitude for the farmer map",
                max_length=80,
            ),
        ),
    ]
