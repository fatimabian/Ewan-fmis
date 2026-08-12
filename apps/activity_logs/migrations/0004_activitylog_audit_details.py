from datetime import timedelta

from django.db import migrations, models


def backfill_farmer_audit_details(apps, schema_editor):
    ActivityLog = apps.get_model("activity_logs", "ActivityLog")
    FarmerUpdateHistory = apps.get_model("farmers", "FarmerUpdateHistory")

    for history in FarmerUpdateHistory.objects.select_related("farmer").all():
        candidates = ActivityLog.objects.filter(
            actor_id=history.actor_id,
            module__in=("Farmers", "Farm Parcels", "Crops"),
            created_at__gte=history.created_at,
            created_at__lte=history.created_at + timedelta(seconds=45),
        ).order_by("created_at")
        log = candidates.first()
        if log is None:
            continue
        reason = {
            "CORRECTION": "A - Correction",
            "REMOVAL": "B - Removal",
            "ADDITION": "C - Additional / New Information",
            "OTHER": "Other",
        }.get(history.change_reason, history.change_reason)
        if history.remarks:
            reason = f"{reason} - {history.remarks}"
        name_parts = [
            history.farmer.first_name,
            history.farmer.middle_name,
            history.farmer.last_name,
            history.farmer.extension_name,
        ]
        log.target_label = " ".join(part for part in name_parts if part).strip()
        log.reason = reason
        log.details = history.changes
        log.save(update_fields=["target_label", "reason", "details"])


class Migration(migrations.Migration):
    dependencies = [
        ("activity_logs", "0003_activitylog_readable_fields"),
        ("farmers", "0007_farmer_fca_membership_farmer_last_updated_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitylog",
            name="target_label",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="activitylog",
            name="reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="activitylog",
            name="details",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(backfill_farmer_audit_details, migrations.RunPython.noop),
    ]
