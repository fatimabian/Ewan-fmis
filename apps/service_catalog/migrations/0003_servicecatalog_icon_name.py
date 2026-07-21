from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("service_catalog", "0002_servicecatalog_availability_and_more")]

    operations = [
        migrations.AddField(
            model_name="servicecatalog",
            name="icon_name",
            field=models.CharField(
                choices=[
                    ("bi-flask", "Laboratory testing"),
                    ("bi-flower1", "Crops and planting"),
                    ("bi-droplet", "Water and irrigation"),
                    ("bi-bug", "Pest management"),
                    ("bi-tools", "Equipment and repair"),
                    ("bi-box-seam", "Farm inputs"),
                    ("bi-mortarboard", "Training and seminars"),
                    ("bi-clipboard2-check", "Registration and certification"),
                    ("bi-shop", "Market assistance"),
                    ("bi-heart-pulse", "Animal and livestock care"),
                    ("bi-people", "Farmer support"),
                    ("bi-journal-text", "General agricultural service"),
                ],
                default="bi-journal-text",
                max_length=40,
            ),
        ),
    ]
