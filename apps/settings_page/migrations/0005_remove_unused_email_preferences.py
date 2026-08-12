from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("settings_page", "0004_system_theme_default"),
    ]

    operations = [
        migrations.RemoveField(model_name="userpreference", name="email_notifications"),
        migrations.RemoveField(model_name="userpreference", name="weekly_summary"),
    ]
