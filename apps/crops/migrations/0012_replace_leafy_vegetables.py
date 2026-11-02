from django.db import migrations


def replace_leafy_vegetables(apps, schema_editor):
    CropRecord = apps.get_model("crops", "CropRecord")
    CropRecord.objects.filter(crop_type__iexact="Leafy Vegetables").update(
        crop_type="Unspecified Leafy Vegetable"
    )


def restore_legacy_leafy_vegetables(apps, schema_editor):
    CropRecord = apps.get_model("crops", "CropRecord")
    CropRecord.objects.filter(
        crop_type__iexact="Unspecified Leafy Vegetable"
    ).update(crop_type="Leafy Vegetables")


class Migration(migrations.Migration):
    dependencies = [("crops", "0011_croprecord_variety")]

    operations = [
        migrations.RunPython(
            replace_leafy_vegetables,
            restore_legacy_leafy_vegetables,
        ),
    ]
