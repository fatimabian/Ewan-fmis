from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("farmers", "0013_alter_farmerdocument_document_type_and_more"),
        ("service_requests", "0003_servicerequesthistory"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicerequest",
            name="scope",
            field=models.CharField(
                choices=[("INDIVIDUAL", "One farmer"), ("BARANGAY", "Barangay")],
                default="INDIVIDUAL",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="target_barangay",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="servicerequest",
            name="farmer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="service_requests",
                to="farmers.farmer",
            ),
        ),
        migrations.AddConstraint(
            model_name="servicerequest",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        scope="INDIVIDUAL",
                        farmer__isnull=False,
                        target_barangay="",
                    )
                    | (
                        models.Q(scope="BARANGAY", farmer__isnull=True)
                        & ~models.Q(target_barangay="")
                    )
                ),
                name="service_request_scope_target_valid",
            ),
        ),
    ]
