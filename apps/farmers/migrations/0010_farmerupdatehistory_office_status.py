from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farmers", "0009_enforce_completed_rsbsa_id")]

    operations = [
        migrations.AlterField(
            model_name="farmerupdatehistory",
            name="update_type",
            field=models.CharField(
                choices=[
                    ("SLIP_A", "Slip A - Personal Information"),
                    ("SLIP_B", "Slip B - Farm Parcel Information"),
                    ("STATUS", "Office Registration Status"),
                ],
                max_length=10,
            ),
        ),
    ]
