from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("authentication", "0005_customuser_deleted_account_retention")]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="mfa_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="customuser",
            name="mfa_secret",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="mfa_recovery_codes",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="customuser",
            name="mfa_last_counter",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="mfa_version",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
