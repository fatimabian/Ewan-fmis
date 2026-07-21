from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crops", "0002_rsbsa_crop_fields")]

    operations = [
        migrations.AddField(
            model_name="croprecord",
            name="image",
            field=models.ImageField(blank=True, upload_to="crop_photos/"),
        ),
    ]
