from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("farmers", "0014_farmer_is_association_member")]

    operations = [
        migrations.AlterField(
            model_name="farmer",
            name="livelihood",
            field=models.CharField(
                choices=[
                    ("FARMER", "Crop Farmer"),
                    ("LIVESTOCK", "Livestock Raiser"),
                    ("POULTRY", "Poultry Raiser"),
                    ("FARMWORKER", "Farm Worker / Laborer"),
                    ("FISHERFOLK", "Fisherfolk"),
                    ("AGRI_YOUTH", "Agri-Youth"),
                ],
                default="FARMER",
                max_length=20,
            ),
        ),
    ]
