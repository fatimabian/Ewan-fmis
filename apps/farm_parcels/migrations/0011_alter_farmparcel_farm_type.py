from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("farm_parcels", "0010_alter_farmparcel_ownership_document"),
    ]

    operations = [
        migrations.AlterField(
            model_name="farmparcel",
            name="farm_type",
            field=models.CharField(blank=True, default="", max_length=180),
        ),
    ]
