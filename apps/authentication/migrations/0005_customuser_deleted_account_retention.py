from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("authentication", "0004_customuser_activation_pending")]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="customuser",
            name="deleted_display_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="customuser",
            name="deleted_username",
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
