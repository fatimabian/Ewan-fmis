from django.db import migrations, models


def make_existing_logs_readable(apps, schema_editor):
    ActivityLog = apps.get_model("activity_logs", "ActivityLog")
    labels = [("/catalog/", "Service Catalog Updated", "Service Catalogs"), ("/farmers/", "Farmer Record Updated", "Farmers"), ("/parcels/", "Farm Parcel Updated", "Farm Parcels"), ("/crops/", "Crop Record Updated", "Crops"), ("/requests/", "Service Request Updated", "Service Requests"), ("/accounts/", "User Account Updated", "User Accounts"), ("/settings/", "Account Settings Updated", "Settings")]
    for log in ActivityLog.objects.all():
        title, module = "System Record Updated", "FMIS"
        for fragment, item_title, item_module in labels:
            if fragment in log.path:
                title, module = item_title, item_module
                break
        if log.actor:
            actor_name = " ".join(part for part in [log.actor.first_name, log.actor.last_name] if part) or log.actor.username
        else:
            actor_name = "A user"
        log.title = title
        log.module = module
        log.description = f"{actor_name} updated a record in {module}."
        log.status = "Success"
        log.save(update_fields=["title", "module", "description", "status"])


class Migration(migrations.Migration):
    dependencies = [("activity_logs", "0002_initial")]

    operations = [
        migrations.AddField(model_name="activitylog", name="title", field=models.CharField(blank=True, max_length=150)),
        migrations.AddField(model_name="activitylog", name="description", field=models.CharField(blank=True, max_length=255)),
        migrations.AddField(model_name="activitylog", name="module", field=models.CharField(blank=True, max_length=100)),
        migrations.AddField(model_name="activitylog", name="status", field=models.CharField(default="Success", max_length=20)),
        migrations.RunPython(make_existing_logs_readable, migrations.RunPython.noop),
    ]
