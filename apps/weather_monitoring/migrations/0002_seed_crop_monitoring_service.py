from django.db import migrations


def seed_service(apps, schema_editor):
    ServiceCatalog = apps.get_model("service_catalog", "ServiceCatalog")
    ServiceCatalog.objects.update_or_create(
        code="CROP-MONITOR",
        defaults={
            "name": "Crop Monitoring Support",
            "category": "Technical Services",
            "description": "Field monitoring support following a reviewed area alert.",
            "processing_time": "Subject to staff scheduling",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("weather_monitoring", "0001_initial"),
        ("service_catalog", "0005_retire_legacy_sample_service"),
    ]

    operations = [migrations.RunPython(seed_service, migrations.RunPython.noop)]
