from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("authentication", "0003_merge_20260713_1559"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="activation_pending",
            field=models.BooleanField(
                default=False,
                help_text="New staff account must verify its email OTP before first access.",
            ),
        ),
    ]
