from django.db.models import Q

from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
from apps.service_requests.models import ServiceRequest


SYNTHETIC_REMARKS_PREFIX = "FMIS-DEMO-DATA:"
SYNTHETIC_RSBSA_PREFIX = "SYNTH-RSBSA-"
LEGACY_SYNTHETIC_RSBSA_PREFIX = "DEMO-RSBSA-"


def synthetic_farmers():
    return Farmer.objects.filter(
        Q(remarks__startswith=SYNTHETIC_REMARKS_PREFIX)
        | Q(rsbsa_number__startswith=SYNTHETIC_RSBSA_PREFIX)
        | Q(rsbsa_number__startswith=LEGACY_SYNTHETIC_RSBSA_PREFIX)
    ).distinct()


def delete_synthetic_data():
    farmer_ids = list(synthetic_farmers().values_list("pk", flat=True))
    if not farmer_ids:
        return 0

    Intervention.objects.filter(farmer_id__in=farmer_ids).delete()
    InterventionRecipient.objects.filter(farmer_id__in=farmer_ids).delete()
    ServiceRequest.objects.filter(farmer_id__in=farmer_ids).delete()
    Farmer.objects.filter(pk__in=farmer_ids).delete()
    return len(farmer_ids)

