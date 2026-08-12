from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("settings_page", "0005_remove_unused_email_preferences"),
    ]

    operations = [
        migrations.CreateModel(
            name="BackupRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("RUNNING", "In progress"), ("VERIFIED", "Verified"), ("FAILED", "Needs attention")], default="RUNNING", max_length=20)),
                ("storage", models.CharField(blank=True, max_length=100)),
                ("archive_name", models.CharField(blank=True, max_length=255)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("checksum", models.CharField(blank=True, max_length=64)),
                ("offsite", models.BooleanField(default=False)),
                ("media_files", models.PositiveIntegerField(default=0)),
                ("retained_copies", models.PositiveIntegerField(default=0)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"ordering": ["-started_at", "-pk"]},
        ),
    ]
