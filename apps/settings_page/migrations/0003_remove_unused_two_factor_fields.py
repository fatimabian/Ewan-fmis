from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("settings_page", "0002_systemsetting")]

    operations = [
        migrations.RemoveField(
            model_name="userpreference",
            name="two_factor_enabled",
        ),
        migrations.RemoveField(
            model_name="systemsetting",
            name="two_factor_required",
        ),
    ]
