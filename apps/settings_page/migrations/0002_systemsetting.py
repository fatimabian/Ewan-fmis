from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("settings_page", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="SystemSetting",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("system_name", models.CharField(default="FMIS - Office of Agriculture", max_length=150)),
                ("timezone", models.CharField(default="Asia/Manila", max_length=100)),
                ("default_language", models.CharField(default="English", max_length=30)),
                ("session_timeout", models.PositiveIntegerField(default=15)),
                ("automated_backups", models.BooleanField(default=True)),
                ("two_factor_required", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
