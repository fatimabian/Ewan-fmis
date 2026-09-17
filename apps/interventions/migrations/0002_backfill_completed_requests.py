from django.db import migrations
from django.utils import timezone


TYPE_BY_SERVICE_CODE = {
    "SEED": "SEEDS",
    "PLANT-MAT": "SEEDS",
    "FERTILIZER": "FERTILIZER",
    "MACHINERY": "EQUIPMENT",
    "TRAINING": "TRAINING",
    "SOIL-TEST": "TECHNICAL",
    "PEST-DISEASE": "TECHNICAL",
    "CROP-TECH": "TECHNICAL",
    "IRRIGATION": "TECHNICAL",
    "LIVESTOCK-VET": "LIVESTOCK",
    "ANIMAL-DISP": "LIVESTOCK",
    "CREDIT": "FINANCIAL",
}


def create_missing_interventions(apps, schema_editor):
    ServiceRequest = apps.get_model("service_requests", "ServiceRequest")
    Intervention = apps.get_model("interventions", "Intervention")
    completed = ServiceRequest.objects.filter(status="COMPLETED").select_related("service")
    for request in completed.iterator():
        if Intervention.objects.filter(service_request_id=request.pk).exists():
            continue
        Intervention.objects.create(
            farmer_id=request.farmer_id,
            service_request_id=request.pk,
            intervention_type=TYPE_BY_SERVICE_CODE.get(request.service.code, "OTHER"),
            intervention_date=timezone.localdate(),
            description=request.subject[:240],
            remarks=request.notes[:1000],
            recorded_by_id=request.assigned_to_id,
            provider="Office for Agricultural Services",
        )


class Migration(migrations.Migration):
    dependencies = [("interventions", "0001_initial")]

    operations = [migrations.RunPython(create_missing_interventions, migrations.RunPython.noop)]
