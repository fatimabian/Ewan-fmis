from django.db import migrations, models


def use_system_theme_for_existing_preferences(apps, schema_editor):
    UserPreference = apps.get_model("settings_page", "UserPreference")
    UserPreference.objects.filter(theme="light").update(theme="system")


def restore_light_theme(apps, schema_editor):
    UserPreference = apps.get_model("settings_page", "UserPreference")
    UserPreference.objects.filter(theme="system").update(theme="light")


class Migration(migrations.Migration):
    dependencies = [
        ("settings_page", "0003_remove_unused_two_factor_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userpreference",
            name="theme",
            field=models.CharField(
                choices=[("light", "Light"), ("dark", "Dark"), ("system", "System")],
                default="system",
                max_length=10,
            ),
        ),
        migrations.RunPython(use_system_theme_for_existing_preferences, restore_light_theme),
    ]
