from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("service_requests", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="servicerequest",
            name="subject",
            field=models.CharField(default="Agricultural service request", max_length=180),
        ),
        migrations.AddField(
            model_name="servicerequest",
            name="priority",
            field=models.CharField(
                choices=[("LOW", "Low"), ("MEDIUM", "Medium"), ("HIGH", "High")],
                default="MEDIUM",
                max_length=10,
            ),
        ),
    ]
