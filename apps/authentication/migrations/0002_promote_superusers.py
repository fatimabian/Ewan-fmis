from django.db import migrations


def promote_existing_superusers(apps, schema_editor):
    CustomUser = apps.get_model("authentication", "CustomUser")
    CustomUser.objects.filter(is_superuser=True).exclude(role="ADMIN").update(role="ADMIN")


class Migration(migrations.Migration):
    dependencies = [("authentication", "0001_initial")]
    operations = [migrations.RunPython(promote_existing_superusers, migrations.RunPython.noop)]
