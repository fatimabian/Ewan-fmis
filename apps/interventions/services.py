from django.utils import timezone

from .models import Intervention


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
    """Create exactly one operational intervention when a request is completed."""
    existing = service_request.interventions.order_by("pk").first()
    if existing:
        return existing, False

    intervention = Intervention.objects.create(
        farmer=service_request.farmer,
        service_request=service_request,
        intervention_type=INTERVENTION_TYPE_BY_SERVICE_CODE.get(
            service_request.service.code,
            "OTHER",
        ),
        intervention_date=timezone.localdate(),
        description=service_request.subject[:240],
        remarks=service_request.notes[:1000],
        recorded_by=actor or service_request.assigned_to,
    )
    return intervention, True
