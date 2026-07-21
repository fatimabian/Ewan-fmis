from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farm_parcels", "0001_initial")]

    operations = [
        migrations.AddField(model_name="farmparcel", name="parcel_name", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="farmparcel", name="land_type", field=models.CharField(choices=[("FLATLAND", "Flatland"), ("UPLAND", "Upland"), ("LOWLAND", "Lowland")], default="FLATLAND", max_length=30)),
        migrations.AddField(model_name="farmparcel", name="is_active", field=models.BooleanField(default=True)),
    ]
