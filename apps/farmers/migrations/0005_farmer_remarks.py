from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farmers", "0004_approve_existing_farmer_records")]
    operations = [
        migrations.AddField(
            model_name="farmer",
            name="remarks",
            field=models.TextField(blank=True, help_text="Internal agricultural-service notes; do not enter unsupported sensitive information.", max_length=1000),
        ),
    ]
