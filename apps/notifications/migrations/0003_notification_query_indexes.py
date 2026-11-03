from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notifications", "0002_plain_language_notifications"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["recipient", "is_read"],
                name="notif_recipient_read_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(
                fields=["recipient", "-created_at", "-id"],
                name="notif_recipient_recent_idx",
            ),
        ),
    ]
