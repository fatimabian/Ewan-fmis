from django.utils import timezone

from .models import Intervention, InterventionRecipient


INTERVENTION_TYPE_BY_SERVICE_CODE = {
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


def ensure_completed_request_intervention(service_request, actor=None):
    """Create or complete one operational intervention for a completed request."""
    intervention = service_request.interventions.order_by("pk").first()
    created = intervention is None
    if created:
        intervention = Intervention(
            service_request=service_request,
            intervention_date=timezone.localdate(),
            provider="Office for Agricultural Services",
        )
    intervention.farmer = service_request.farmer
    intervention.scope = "INDIVIDUAL"
    intervention.status = "COMPLETED"
    intervention.intervention_type = INTERVENTION_TYPE_BY_SERVICE_CODE.get(
        service_request.service.code,
        "OTHER",
    )
    intervention.description = (
        service_request.notes.strip() or service_request.subject
    )[:240]
    intervention.remarks = service_request.notes[:1000]
    intervention.recorded_by = actor or service_request.assigned_to
    intervention.is_active = True
    intervention.save()
    intervention.recipients.exclude(farmer=service_request.farmer).update(is_active=False)
    InterventionRecipient.objects.update_or_create(
        intervention=intervention,
        farmer=service_request.farmer,
        defaults={
            "status": "RECEIVED",
            "received_at": intervention.intervention_date,
            "is_active": True,
        },
    )
    return intervention, created
