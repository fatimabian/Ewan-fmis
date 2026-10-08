from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def create_legacy_recipients(apps, schema_editor):
    Intervention = apps.get_model("interventions", "Intervention")
    Recipient = apps.get_model("interventions", "InterventionRecipient")
    for item in Intervention.objects.exclude(farmer_id=None).iterator():
        Recipient.objects.get_or_create(
            intervention_id=item.pk,
            farmer_id=item.farmer_id,
            defaults={"status": "RECEIVED", "is_active": True},
        )


class Migration(migrations.Migration):
    dependencies = [("interventions", "0002_backfill_completed_requests")]

    operations = [
        migrations.AlterField(
            model_name="intervention",
            name="farmer",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="interventions", to="farmers.farmer"),
        ),
        migrations.AddField(
            model_name="intervention", name="scope",
            field=models.CharField(choices=[("INDIVIDUAL", "One farmer"), ("SELECTED", "Selected farmers"), ("BARANGAY", "All active farmers in a barangay"), ("ALL", "All active farmers")], default="INDIVIDUAL", max_length=12),
        ),
        migrations.AddField(
            model_name="intervention", name="target_barangay",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name="intervention", name="status",
            field=models.CharField(choices=[("DRAFT", "Draft"), ("SCHEDULED", "Scheduled"), ("ONGOING", "Ongoing"), ("COMPLETED", "Completed"), ("CANCELLED", "Cancelled")], default="COMPLETED", max_length=12),
        ),
        migrations.CreateModel(
            name="InterventionRecipient",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("RECEIVED", "Received"), ("DECLINED", "Declined"), ("NO_SHOW", "No-show")], default="PENDING", max_length=12)),
                ("quantity_received", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True, validators=[django.core.validators.MinValueValidator(0)])),
                ("received_at", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("farmer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="intervention_recipients", to="farmers.farmer")),
                ("intervention", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recipients", to="interventions.intervention")),
            ],
            options={"ordering": ["farmer__last_name", "farmer__first_name", "pk"]},
        ),
        migrations.AddConstraint(
            model_name="interventionrecipient",
            constraint=models.UniqueConstraint(fields=("intervention", "farmer"), name="unique_intervention_recipient"),
        ),
        migrations.RunPython(create_legacy_recipients, migrations.RunPython.noop),
    ]
