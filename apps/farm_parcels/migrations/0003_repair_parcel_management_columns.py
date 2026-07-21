from django.db import migrations


def add_missing_parcel_columns(apps, schema_editor):
    """Repair MySQL tables whose migration history is ahead of their columns."""
    FarmParcel = apps.get_model("farm_parcels", "FarmParcel")
    table_name = FarmParcel._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }

    for field_name in ("parcel_name", "land_type", "is_active"):
        if field_name not in existing_columns:
            schema_editor.add_field(FarmParcel, FarmParcel._meta.get_field(field_name))


class Migration(migrations.Migration):
    dependencies = [("farm_parcels", "0002_parcel_management_fields")]

    operations = [migrations.RunPython(add_missing_parcel_columns, migrations.RunPython.noop)]
