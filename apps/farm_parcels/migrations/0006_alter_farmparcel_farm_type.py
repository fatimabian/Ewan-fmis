from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm_parcels', '0005_remove_farmparcel_is_organic_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='farmparcel',
            name='farm_type',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
