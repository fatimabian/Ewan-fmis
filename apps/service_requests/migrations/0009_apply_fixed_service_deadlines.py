from datetime import timedelta

from django.db import migrations


FIXED_TARGET_HOURS = {
    "HIGH": (24, 72),
    "MEDIUM": (72, 96),
    "LOW": (120, 168),
}


def apply_fixed_deadlines(apps, schema_editor):
    ServiceRequest = apps.get_model("service_requests", "ServiceRequest")
    pending_updates = []
    for request in ServiceRequest.objects.exclude(
        status__in=("COMPLETED", "CANCELLED")
    ).only("pk", "priority", "created_at", "first_response_due_at", "due_at"):
        response_hours, completion_hours = FIXED_TARGET_HOURS[request.priority]
        request.first_response_due_at = request.created_at + timedelta(hours=response_hours)
        request.due_at = request.created_at + timedelta(hours=completion_hours)
        pending_updates.append(request)
    if pending_updates:
        ServiceRequest.objects.bulk_update(
            pending_updates,
            ("first_response_due_at", "due_at"),
            batch_size=500,
        )


class Migration(migrations.Migration):
    dependencies = [("service_requests", "0008_servicerequest_source")]

    operations = [migrations.RunPython(apply_fixed_deadlines, migrations.RunPython.noop)]
