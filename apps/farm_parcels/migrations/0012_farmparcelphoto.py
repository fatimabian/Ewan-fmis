import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.farm_parcels.models


def move_crop_photos_to_parcel_gallery(apps, schema_editor):
    CropRecord = apps.get_model("crops", "CropRecord")
    FarmParcelPhoto = apps.get_model("farm_parcels", "FarmParcelPhoto")
    for crop in CropRecord.objects.exclude(image="").iterator():
        FarmParcelPhoto.objects.get_or_create(
            parcel_id=crop.parcel_id,
            image=crop.image.name,
            defaults={"caption": f"Field photo imported from {crop.crop_type}"},
        )


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("crops", "0006_croprecord_archive_fields"),
        ("farm_parcels", "0011_alter_farmparcel_farm_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="FarmParcelPhoto",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "image",
                    models.ImageField(upload_to=apps.farm_parcels.models.parcel_photo_upload_path),
                ),
                ("caption", models.CharField(blank=True, max_length=180)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("is_active", models.BooleanField(default=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                (
                    "archived_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="archived_parcel_photos",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "parcel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="photos",
                        to="farm_parcels.farmparcel",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_parcel_photos",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-pk"]},
        ),
        migrations.RunPython(move_crop_photos_to_parcel_gallery, migrations.RunPython.noop),
    ]
