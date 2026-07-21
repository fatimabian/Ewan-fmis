from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farm_parcels", "0003_repair_parcel_management_columns")]

    operations = [
        migrations.AlterField(model_name="farmparcel", name="ownership_type", field=models.CharField(choices=[("OWNED", "Registered Owner"), ("TENANT", "Tenant"), ("LEASED", "Lessee"), ("ARB", "Agrarian Reform Beneficiary"), ("OTHER", "Other")], max_length=30)),
        migrations.AddField(model_name="farmparcel", name="municipality", field=models.CharField(default="Rosario", max_length=100)),
        migrations.AddField(model_name="farmparcel", name="province", field=models.CharField(default="Batangas", max_length=100)),
        migrations.AddField(model_name="farmparcel", name="farm_type", field=models.CharField(choices=[("IRRIGATED", "Irrigated"), ("RAINFED_UPLAND", "Rainfed Upland"), ("RAINFED_LOWLAND", "Rainfed Lowland"), ("NOT_APPLICABLE", "Not Applicable")], default="IRRIGATED", max_length=30)),
        migrations.AddField(model_name="farmparcel", name="within_ancestral_domain", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="farmparcel", name="agrarian_reform_beneficiary", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="farmparcel", name="ownership_document", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="farmparcel", name="land_owner_name", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="farmparcel", name="land_owner_registered_rsbsa", field=models.BooleanField(blank=True, null=True)),
        migrations.AddField(model_name="farmparcel", name="is_rsbsa_recorded", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="farmparcel", name="is_organic", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="farmparcel", name="georef_id", field=models.CharField(blank=True, max_length=80)),
    ]
