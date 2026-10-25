from django.db import migrations


ROSARIO_DEMO_COMMODITIES = (
    "Rice", "Rice", "Rice", "Rice", "Rice", "Rice",
    "Corn", "Corn", "Corn",
    "Banana", "Banana", "Mango", "Mango", "Coconut", "Coconut",
    "Squash", "Squash", "Ginger", "Turmeric", "Calamansi / Mandarin",
    "Swine", "Swine", "Poultry", "Poultry", "Dairy Carabao",
)
ANIMAL_COMMODITIES = {"Swine", "Poultry", "Dairy Carabao"}
SCHEDULES = ("January - April", "May - August", "September - December")


def standardize_demo_commodities(apps, schema_editor):
    CropRecord = apps.get_model("crops", "CropRecord")
    records = list(
        CropRecord.objects.filter(
            parcel__farmer__remarks__startswith="FMIS-DEMO-DATA:"
        )
        .select_related("parcel")
        .order_by("pk")
    )
    for index, record in enumerate(records):
        commodity = ROSARIO_DEMO_COMMODITIES[index % len(ROSARIO_DEMO_COMMODITIES)]
        record.crop_type = commodity
        if commodity in ANIMAL_COMMODITIES:
            record.area_hectares = None
            record.number_of_heads = 10 + (index % 190)
            record.cropping_schedule = ""
            record.is_intercrop = False
        else:
            record.area_hectares = record.area_hectares or record.parcel.area_hectares
            record.number_of_heads = None
            record.cropping_schedule = SCHEDULES[index % len(SCHEDULES)]
    if records:
        CropRecord.objects.bulk_update(
            records,
            [
                "crop_type",
                "area_hectares",
                "number_of_heads",
                "cropping_schedule",
                "is_intercrop",
            ],
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("crops", "0009_alter_croprecord_cropping_schedule"),
    ]

    operations = [
        migrations.RunPython(standardize_demo_commodities, migrations.RunPython.noop),
    ]
