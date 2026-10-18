from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
from apps.service_requests.models import ServiceRequest


SYNTHETIC_REMARKS_PREFIX = "FMIS-DEMO-DATA:"
SYNTHETIC_RSBSA_PREFIX = "SYNTH-RSBSA-"


def synthetic_farmers():
    return Farmer.objects.filter(remarks__startswith=SYNTHETIC_REMARKS_PREFIX)


def delete_synthetic_data():
    farmer_ids = list(synthetic_farmers().values_list("pk", flat=True))
    if not farmer_ids:
        return 0

    Intervention.objects.filter(farmer_id__in=farmer_ids).delete()
    InterventionRecipient.objects.filter(farmer_id__in=farmer_ids).delete()
    ServiceRequest.objects.filter(farmer_id__in=farmer_ids).delete()
    Farmer.objects.filter(pk__in=farmer_ids).delete()
    return len(farmer_ids)

