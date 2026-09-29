from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings_page", "0006_backuprun"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="profile_photo",
            field=models.ImageField(blank=True, upload_to="account_profiles/"),
        ),
    ]
