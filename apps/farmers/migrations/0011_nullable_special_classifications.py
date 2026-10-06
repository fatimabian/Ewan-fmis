from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("farmers", "0010_farmerupdatehistory_office_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="farmer",
            name="is_indigenous",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name="farmer",
            name="is_pwd",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
        migrations.AlterField(
            model_name="farmer",
            name="is_four_ps",
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
