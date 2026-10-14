from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farmers", "0012_farmer_created_by")]

    operations = [
        migrations.AlterField(
            model_name="farmerdocument",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("RSBSA_FORM", "Scanned RSBSA Enrollment Form"),
                    ("VALID_ID", "Valid ID"),
                    ("PROOF_OF_ADDRESS", "Proof of Address"),
                    ("OWNERSHIP", "Ownership / Tenure Document"),
                    ("ADDITIONAL", "Additional Supporting Document"),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="farmerupdatehistory",
            name="update_type",
            field=models.CharField(
                choices=[
                    ("SLIP_A", "Update Record - Farmer Information"),
                    ("SLIP_B", "Update Record - Farm Parcel Information"),
                    ("STATUS", "Office Registration Status"),
                ],
                max_length=10,
            ),
        ),
    ]
