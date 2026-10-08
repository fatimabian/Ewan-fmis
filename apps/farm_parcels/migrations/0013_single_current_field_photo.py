from django.db import migrations
from django.utils import timezone


def archive_extra_field_photos(apps, schema_editor):
    FarmParcelPhoto = apps.get_model("farm_parcels", "FarmParcelPhoto")
    parcel_ids = (
        FarmParcelPhoto.objects.filter(is_active=True)
        .order_by()
        .values_list("parcel_id", flat=True)
        .distinct()
    )
    archived_at = timezone.now()
    for parcel_id in parcel_ids.iterator():
        active_ids = list(
            FarmParcelPhoto.objects.filter(parcel_id=parcel_id, is_active=True)
            .order_by("-created_at", "-pk")
            .values_list("pk", flat=True)
        )
        if len(active_ids) > 1:
            FarmParcelPhoto.objects.filter(pk__in=active_ids[1:]).update(
                is_active=False,
                archived_at=archived_at,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("farm_parcels", "0012_farmparcelphoto"),
    ]

    operations = [
        migrations.RunPython(archive_extra_field_photos, migrations.RunPython.noop),
    ]
