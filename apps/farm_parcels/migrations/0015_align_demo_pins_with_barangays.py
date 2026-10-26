from django.db import migrations


SYNTHETIC_REMARKS_PREFIX = "FMIS-DEMO-DATA:"


def align_demo_pins_with_barangays(apps, schema_editor):
    from apps.farm_parcels.demo_locations import rosario_demo_coordinates_for_barangays

    FarmParcel = apps.get_model("farm_parcels", "FarmParcel")
    Farmer = apps.get_model("farmers", "Farmer")
    parcels = list(
        FarmParcel.objects.filter(remarks__startswith=SYNTHETIC_REMARKS_PREFIX)
        .select_related("farmer")
        .order_by("barangay", "pk")
    )
    coordinates = rosario_demo_coordinates_for_barangays(
        [parcel.barangay or parcel.farmer.barangay for parcel in parcels]
    )
    farmer_coordinate = {}
    for parcel, point in zip(parcels, coordinates):
        parcel.coordinates = point
        farmer_coordinate[parcel.farmer_id] = point
    if parcels:
        FarmParcel.objects.bulk_update(parcels, ["coordinates"], batch_size=500)

    farmers = list(Farmer.objects.filter(pk__in=farmer_coordinate))
    for farmer in farmers:
        farmer.location_coordinates = farmer_coordinate[farmer.pk]
    if farmers:
        Farmer.objects.bulk_update(farmers, ["location_coordinates"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("farm_parcels", "0014_distribute_demo_parcel_pins")]
    operations = [
        migrations.RunPython(align_demo_pins_with_barangays, migrations.RunPython.noop),
    ]
