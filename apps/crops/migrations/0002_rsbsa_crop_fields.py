from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("crops", "0001_initial")]

    operations = [
        migrations.AlterField(model_name="croprecord", name="planting_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="croprecord", name="cropping_schedule", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="croprecord", name="number_of_heads", field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name="croprecord", name="is_organic", field=models.BooleanField(default=False)),
    ]
