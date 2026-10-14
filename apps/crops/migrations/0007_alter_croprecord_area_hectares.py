from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("crops", "0006_croprecord_archive_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="croprecord",
            name="area_hectares",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=10, null=True
            ),
        ),
    ]
