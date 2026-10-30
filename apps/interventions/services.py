from django.db import transaction
from django.utils import timezone

from .models import Intervention, InterventionRecipient
from apps.farmers.models import Farmer


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


def complete_registered_request_intervention(service_request, actor=None):
    """Complete the request's existing active intervention without creating one."""
    intervention = service_request.interventions.filter(is_active=True).order_by("pk").first()
    if not intervention:
        return None
    intervention.scope = service_request.scope
    intervention.farmer = (
        service_request.farmer if service_request.scope == "INDIVIDUAL" else None
    )
    intervention.target_barangay = (
        service_request.target_barangay if service_request.scope == "BARANGAY" else ""
    )
    intervention.target_association = (
        service_request.target_association
        if service_request.scope == "ASSOCIATION"
        else ""
    )
    intervention.walk_in_name = (
        service_request.walk_in_name if service_request.scope == "WALK_IN" else ""
    )
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
    if service_request.scope == "BARANGAY":
        recipients = Farmer.objects.filter(
            is_active=True,
            barangay=service_request.target_barangay,
        )
    elif service_request.scope == "ASSOCIATION":
        recipients = Farmer.objects.filter(
            is_active=True,
            is_association_member=True,
            fca_membership=service_request.target_association,
        )
    elif service_request.scope == "INDIVIDUAL":
        recipients = Farmer.objects.filter(pk=service_request.farmer_id)
    else:
        recipients = Farmer.objects.none()
    recipient_ids = list(recipients.values_list("pk", flat=True))
    intervention.recipients.exclude(farmer_id__in=recipient_ids).update(is_active=False)
    for farmer_id in recipient_ids:
        InterventionRecipient.objects.update_or_create(
            intervention=intervention,
            farmer_id=farmer_id,
            defaults={
                "status": "RECEIVED",
                "received_at": intervention.intervention_date,
                "is_active": True,
            },
        )
    return intervention


@transaction.atomic
def ensure_inventory_release_intervention(
    service_request, *, actor, description, quantity, unit
):
    """Return one delivered intervention for a request, creating it when needed."""
    service_request = type(service_request).objects.select_for_update().select_related(
        "farmer", "service", "assigned_to"
    ).get(pk=service_request.pk)
    intervention = (
        service_request.interventions.filter(is_active=True)
        .order_by("pk")
        .first()
    )
    if intervention is None:
        intervention = Intervention.objects.create(
            service_request=service_request,
            scope=service_request.scope,
            farmer=(
                service_request.farmer
                if service_request.scope == "INDIVIDUAL"
                else None
            ),
            target_barangay=(
                service_request.target_barangay
                if service_request.scope == "BARANGAY"
                else ""
            ),
            target_association=(
                service_request.target_association
                if service_request.scope == "ASSOCIATION"
                else ""
            ),
            walk_in_name=(
                service_request.walk_in_name
                if service_request.scope == "WALK_IN"
                else ""
            ),
            status="COMPLETED",
            intervention_type=INTERVENTION_TYPE_BY_SERVICE_CODE.get(
                service_request.service.code, "OTHER"
            ),
            intervention_date=timezone.localdate(),
            description=description[:240],
            quantity=quantity,
            unit=unit,
            provider="Office for Agricultural Services",
            recorded_by=actor,
        )
    else:
        intervention.quantity = quantity
        intervention.unit = unit
        intervention.description = description[:240]
        intervention.intervention_date = intervention.intervention_date or timezone.localdate()
        intervention.save(update_fields=[
            "quantity", "unit", "description", "intervention_date", "updated_at"
        ])

    # Synchronize request-derived coverage and a fixed recipient snapshot for both
    # newly created and previously existing interventions.
    intervention = complete_registered_request_intervention(
        service_request, actor=actor
    )

    # The request is fulfilled by the completed release/intervention chain.
    if service_request.status != "COMPLETED":
        service_request.status = "COMPLETED"
        service_request.save(update_fields=[
            "status", "first_responded_at", "completed_at", "updated_at"
        ])
    return intervention
