import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crops", "0007_alter_croprecord_area_hectares")]

    operations = [
        migrations.AddField(
            model_name="croprecord",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
            ),
            preserve_default=False,
        ),
    ]
