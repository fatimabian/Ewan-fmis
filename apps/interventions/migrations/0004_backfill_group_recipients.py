from collections import defaultdict

from django.db import migrations


def backfill_group_recipients(apps, schema_editor):
    """Create the missing fixed snapshots for legacy barangay/all-farmer records."""
    Farmer = apps.get_model("farmers", "Farmer")
    Intervention = apps.get_model("interventions", "Intervention")
    Recipient = apps.get_model("interventions", "InterventionRecipient")

    active_farmer_ids = []
    farmer_ids_by_barangay = defaultdict(list)
    for farmer_id, barangay in Farmer.objects.filter(is_active=True).values_list(
        "pk", "barangay"
    ):
        active_farmer_ids.append(farmer_id)
        farmer_ids_by_barangay[barangay].append(farmer_id)

    interventions = Intervention.objects.filter(scope__in=("BARANGAY", "ALL"))
    for intervention in interventions.iterator():
        # Existing recipient rows are historical snapshots and must not be replaced.
        if Recipient.objects.filter(
            intervention_id=intervention.pk, is_active=True
        ).exists():
            continue

        farmer_ids = (
            farmer_ids_by_barangay.get(intervention.target_barangay, [])
            if intervention.scope == "BARANGAY"
            else active_farmer_ids
        )
        received = intervention.status == "COMPLETED"
        Recipient.objects.bulk_create(
            [
                Recipient(
                    intervention_id=intervention.pk,
                    farmer_id=farmer_id,
                    status="RECEIVED" if received else "PENDING",
                    received_at=intervention.intervention_date if received else None,
                    is_active=True,
                )
                for farmer_id in farmer_ids
            ],
            batch_size=500,
            ignore_conflicts=True,
        )


class Migration(migrations.Migration):
    dependencies = [("interventions", "0003_intervention_scope_and_recipients")]

    operations = [
        migrations.RunPython(backfill_group_recipients, migrations.RunPython.noop),
    ]
