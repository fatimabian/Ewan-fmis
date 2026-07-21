import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farmers", "0001_initial")]

    operations = [
        migrations.AddField(model_name="farmer", name="middle_name", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="farmer", name="extension_name", field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name="farmer", name="sex", field=models.CharField(blank=True, choices=[("MALE", "Male"), ("FEMALE", "Female")], max_length=10)),
        migrations.AddField(model_name="farmer", name="birth_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="farmer", name="place_of_birth", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="farmer", name="house_lot_purok", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="farmer", name="street_sitio", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="farmer", name="city_municipality", field=models.CharField(default="Rosario", max_length=100)),
        migrations.AddField(model_name="farmer", name="province", field=models.CharField(default="Batangas", max_length=100)),
        migrations.AddField(model_name="farmer", name="region", field=models.CharField(default="CALABARZON Region IV-A", max_length=100)),
        migrations.AddField(model_name="farmer", name="mother_maiden_name", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="farmer", name="civil_status", field=models.CharField(blank=True, choices=[("SINGLE", "Single"), ("MARRIED", "Married"), ("WIDOWED", "Widowed"), ("SEPARATED", "Separated")], max_length=15)),
        migrations.AddField(model_name="farmer", name="spouse_name", field=models.CharField(blank=True, max_length=180)),
        migrations.AddField(model_name="farmer", name="highest_education", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="farmer", name="valid_id_type", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="farmer", name="valid_id_number", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="farmer", name="religion", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="farmer", name="is_indigenous", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="farmer", name="indigenous_group", field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name="farmer", name="is_pwd", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="farmer", name="is_four_ps", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="farmer", name="livelihood", field=models.CharField(choices=[("FARMER", "Farmer"), ("FARMWORKER", "Farm Worker / Laborer"), ("FISHERFOLK", "Fisherfolk"), ("AGRI_YOUTH", "Agri-Youth")], default="FARMER", max_length=20)),
        migrations.AddField(model_name="farmer", name="activities", field=models.TextField(blank=True, help_text="Comma-separated RSBSA livelihood activities")),
        migrations.AddField(model_name="farmer", name="rsbsa_number", field=models.CharField(blank=True, max_length=40, null=True, unique=True)),
        migrations.AddField(model_name="farmer", name="registration_status", field=models.CharField(choices=[("PENDING", "Pending Review"), ("APPROVED", "Approved"), ("REJECTED", "Needs Correction")], default="APPROVED", max_length=12)),
        migrations.AddField(model_name="farmer", name="consent_given", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="farmer", name="submitted_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.CreateModel(
            name="FarmerDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("document_type", models.CharField(choices=[("VALID_ID", "Valid ID"), ("PROOF_OF_ADDRESS", "Proof of Address"), ("OWNERSHIP", "Ownership / Tenure Document"), ("ADDITIONAL", "Additional Supporting Document")], max_length=30)),
                ("description", models.CharField(blank=True, max_length=180)),
                ("file", models.FileField(upload_to="farm_documents/")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("farmer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="farmers.farmer")),
            ],
        ),
    ]
