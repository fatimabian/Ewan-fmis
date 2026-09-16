from django.db import migrations


def retire_legacy_sample_service(apps, schema_editor):
    ServiceCatalog = apps.get_model("service_catalog", "ServiceCatalog")
    ServiceRequest = apps.get_model("service_requests", "ServiceRequest")

    replacement = ServiceCatalog.objects.filter(code="OTHER").first()
    legacy = ServiceCatalog.objects.filter(code="SC-01", name__iexact="geh").first()
    if not legacy:
        return

    if replacement:
        ServiceRequest.objects.filter(service_id=legacy.pk).update(service_id=replacement.pk)
    legacy.is_active = False
    legacy.save(update_fields=["is_active"])


class Migration(migrations.Migration):
    dependencies = [
        ("service_catalog", "0004_seed_canonical_request_types"),
        ("service_requests", "0003_servicerequesthistory"),
    ]

    operations = [
        migrations.RunPython(retire_legacy_sample_service, migrations.RunPython.noop),
    ]
