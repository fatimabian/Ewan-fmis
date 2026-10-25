from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.constants import LIVESTOCK_COMMODITIES, ROSARIO_BARANGAYS
from apps.crops.models import CropRecord
from apps.farm_parcels.models import FarmParcel
from apps.farmers.demo_data import (
    SYNTHETIC_REMARKS_PREFIX,
    SYNTHETIC_RSBSA_PREFIX,
    delete_synthetic_data,
)
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
from apps.interventions.services import INTERVENTION_TYPE_BY_SERVICE_CODE
from apps.service_catalog.models import ServiceCatalog
from apps.service_requests.models import ServiceRequest, ServiceRequestHistory


FIRST_NAMES = (
    ("Ana", "FEMALE"), ("Maria", "FEMALE"), ("Liza", "FEMALE"),
    ("Grace", "FEMALE"), ("Elena", "FEMALE"), ("Rosa", "FEMALE"),
    ("Teresa", "FEMALE"), ("Jocelyn", "FEMALE"), ("Angelica", "FEMALE"),
    ("Sofia", "FEMALE"), ("Jose", "MALE"), ("Juan", "MALE"),
    ("Ramon", "MALE"), ("Roberto", "MALE"), ("Eduardo", "MALE"),
    ("Manuel", "MALE"), ("Antonio", "MALE"), ("Carlos", "MALE"),
    ("Daniel", "MALE"), ("Miguel", "MALE"),
)
MIDDLE_NAMES = (
    "Reyes", "Garcia", "Mendoza", "Torres", "Flores", "Ramos", "Aquino",
    "Castillo", "Navarro", "Santos", "Rivera", "Cruz", "Bautista", "Diaz",
    "Mercado", "Pascual", "Soriano", "Valdez", "Aguilar", "Domingo",
)
LAST_NAMES = (
    "Abad", "Alcantara", "Alvarez", "Arceo", "Bernardo", "Cabral", "Carandang",
    "De Guzman", "Del Rosario", "Evangelista", "Fernandez", "Hernandez", "Lazaro",
    "Magpantay", "Manalo", "Marasigan", "Recto", "Salazar", "Tolentino", "Villanueva",
)
CROPS = (
    "Rice", "Rice", "Rice", "Rice", "Rice", "Rice",
    "Corn", "Corn", "Corn",
    "Banana", "Banana", "Mango", "Mango", "Coconut", "Coconut",
    "Squash", "Squash", "Ginger", "Turmeric", "Calamansi / Mandarin",
    "Swine", "Swine", "Poultry", "Poultry", "Dairy Carabao",
)
SERVICE_CODES = (
    "SEED", "FERTILIZER", "SOIL-TEST", "PEST-DISEASE", "CROP-TECH",
    "IRRIGATION", "MACHINERY", "TRAINING", "CREDIT", "MARKET",
)


def registration_status(index):
    bucket = index % 10
    if bucket < 5:
        return "COMPLETED"
    if bucket < 8:
        return "SUBMITTED"
    if bucket == 8:
        return "ENCODED"
    return "SKIPPED"


class Command(BaseCommand):
    help = "Create realistic synthetic FMIS farmers and linked operational records."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=4700)

    @transaction.atomic
    def handle(self, *args, **options):
        count = options["count"]
        if count < 1 or count > 50000:
            raise CommandError("--count must be between 1 and 50000.")

        services = list(
            ServiceCatalog.objects.filter(code__in=SERVICE_CODES, is_active=True).order_by("code")
        )
        if not services:
            raise CommandError("The agricultural service catalog must be initialized first.")

        replaced = delete_synthetic_data()
        now = timezone.now()
        today = timezone.localdate()
        education = ("Elementary", "High School", "College", "Vocational")
        religions = ("Roman Catholic", "Christian", "Iglesia ni Cristo", "")
        livelihoods = ("FARMER", "FARMER", "FARMWORKER", "AGRI_YOUTH")
        farmers = []
        for index in range(1, count + 1):
            position = index - 1
            first_name, sex = FIRST_NAMES[position % len(FIRST_NAMES)]
            middle_name = MIDDLE_NAMES[(position // len(FIRST_NAMES)) % len(MIDDLE_NAMES)]
            last_name = LAST_NAMES[
                (position // (len(FIRST_NAMES) * len(MIDDLE_NAMES))) % len(LAST_NAMES)
            ]
            status = registration_status(index)
            barangay = ROSARIO_BARANGAYS[position % len(ROSARIO_BARANGAYS)]
            farmers.append(
                Farmer(
                    first_name=first_name,
                    middle_name=middle_name,
                    last_name=last_name,
                    sex=sex,
                    birth_date=date(1953 + (index % 48), 1 + (index % 12), 1 + (index % 27)),
                    place_of_birth=f"{barangay}, Rosario, Batangas",
                    mother_maiden_name=f"{MIDDLE_NAMES[(position + 7) % len(MIDDLE_NAMES)]} {LAST_NAMES[(position + 3) % len(LAST_NAMES)]}",
                    house_lot_purok=f"Purok {1 + (index % 7)}",
                    street_sitio=f"Sitio {1 + (index % 9)}",
                    barangay=barangay,
                    phone_number=f"0998{index:07d}",
                    email=f"{first_name.lower()}.{last_name.lower().replace(' ', '')}.{index}@example.invalid",
                    civil_status=("SINGLE", "MARRIED", "WIDOWED", "SEPARATED")[index % 4],
                    spouse_name=(f"{FIRST_NAMES[(position + 9) % len(FIRST_NAMES)][0]} {last_name}" if index % 4 == 1 else ""),
                    highest_education=education[index % len(education)],
                    valid_id_type=("PhilSys ID", "Voter ID", "Driver License")[index % 3],
                    valid_id_number=f"SYN-{index:09d}",
                    religion=religions[index % len(religions)],
                    is_indigenous=index % 29 == 0,
                    indigenous_group="Tagalog" if index % 29 == 0 else "",
                    is_pwd=index % 37 == 0,
                    is_four_ps=index % 11 == 0,
                    livelihood=livelihoods[index % len(livelihoods)],
                    activities="FARMER_CROPS",
                    remarks=f"{SYNTHETIC_REMARKS_PREFIX} Synthetic training record; batch position {index}.",
                    rsbsa_number=(f"{SYNTHETIC_RSBSA_PREFIX}{index:06d}" if status == "COMPLETED" else None),
                    registration_status=status,
                    consent_given=status != "ENCODED",
                    submitted_at=now if status in {"SUBMITTED", "COMPLETED"} else None,
                    location_coordinates=f"{13.8300 + (index % 80) / 10000:.6f},{121.1900 + (index % 90) / 10000:.6f}",
                    philsys_registered=index % 3 != 0,
                    philsys_pcn=f"SYNPCN{index:012d}" if index % 3 != 0 else "",
                    fca_membership="Rosario Farmers Association" if index % 5 == 0 else "",
                    is_active=index % 23 != 0,
                )
            )
        Farmer.objects.bulk_create(farmers, batch_size=500)

        ownership = ("OWNED", "TENANT", "LEASED", "ARB", "OTHER")
        parcels = []
        for index, farmer in enumerate(farmers, start=1):
            owned = ownership[index % len(ownership)]
            land_type = "LOWLAND" if index % 3 == 0 else "UPLAND"
            parcels.append(
                FarmParcel(
                    farmer=farmer,
                    parcel_name=f"{farmer.barangay} Farm",
                    barangay=farmer.barangay,
                    area_hectares=Decimal("0.50") + Decimal(index % 16) / Decimal("4"),
                    ownership_type=owned,
                    land_type=land_type,
                    farm_type="Irrigated" if index % 2 else f"Rainfed {land_type.title()}",
                    within_ancestral_domain=index % 31 == 0,
                    agrarian_reform_beneficiary=owned == "ARB",
                    ownership_document="Tax Declaration" if owned in {"OWNED", "ARB"} else "",
                    land_owner_name=farmer.full_name if owned == "OWNED" else "Recorded landholder",
                    land_owner_registered_rsbsa=farmer.registration_status == "COMPLETED",
                    land_owner_rsbsa_number=farmer.rsbsa_number or "",
                    is_rsbsa_recorded=farmer.registration_status == "COMPLETED",
                    georef_id=f"ROS-GEO-{index:06d}",
                    gpx_status=("KNOWN", "FORGOT", "NOT_GEOREFERENCED")[index % 3],
                    rotational_tiller=index % 2 == 0,
                    remarks=f"{SYNTHETIC_REMARKS_PREFIX} Synthetic parcel record.",
                    coordinates=f"{13.8300 + (index % 80) / 10000:.6f},{121.1900 + (index % 90) / 10000:.6f}",
                    is_active=index % 19 != 0,
                )
            )
        FarmParcel.objects.bulk_create(parcels, batch_size=500)

        crop_records = []
        for index, parcel in enumerate(parcels, start=1):
            active = index % 17 != 0
            commodity = CROPS[(index - 1) % len(CROPS)]
            animal_commodity = commodity in LIVESTOCK_COMMODITIES
            crop_records.append(
                CropRecord(
                    parcel=parcel,
                    crop_type=commodity,
                    cropping_schedule=("Jan-Apr", "May-Aug", "Sep-Dec")[index % 3],
                    area_hectares=None if animal_commodity else parcel.area_hectares,
                    number_of_heads=(10 + index % 190) if animal_commodity else None,
                    is_organic=index % 8 == 0,
                    is_intercrop=index % 6 == 0,
                    planting_date=date(2026, 1 + (index % 9), 1 + (index % 20)),
                    harvest_date=date(2026, 3 + (index % 9), 1 + (index % 20)),
                    is_active=active,
                    archived_at=None if active else now,
                )
            )
        CropRecord.objects.bulk_create(crop_records, batch_size=500)

        staff = get_user_model().objects.filter(role="STAFF", is_active=True).order_by("pk").first()
        service_requests = []
        request_indexes = []
        request_statuses = ("PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED")
        priorities = ("LOW", "MEDIUM", "HIGH")
        for index, farmer in enumerate(farmers, start=1):
            if index % 3:
                continue
            service = services[index % len(services)]
            service_requests.append(
                ServiceRequest(
                    farmer=farmer,
                    service=service,
                    subject=service.name,
                    priority=priorities[index % len(priorities)],
                    status=request_statuses[(index // 3) % len(request_statuses)],
                    notes=f"{SYNTHETIC_REMARKS_PREFIX} Synthetic request for workflow testing.",
                    assigned_to=staff,
                )
            )
            request_indexes.append(index)
        ServiceRequest.objects.bulk_create(service_requests, batch_size=500)
        ServiceRequestHistory.objects.bulk_create(
            [
                ServiceRequestHistory(
                    service_request=request,
                    actor=staff,
                    action="CREATED",
                    to_status=request.status,
                    changes=[{"field": "Synthetic data", "before": "", "after": "Generated"}],
                )
                for request in service_requests
            ],
            batch_size=500,
        )
        requests_by_index = dict(zip(request_indexes, service_requests))

        intervention_statuses = ("DRAFT", "SCHEDULED", "ONGOING", "COMPLETED", "CANCELLED")
        interventions = []
        for index, farmer in enumerate(farmers, start=1):
            if index % 4:
                continue
            linked_request = requests_by_index.get(index)
            service_code = linked_request.service.code if linked_request else SERVICE_CODES[index % len(SERVICE_CODES)]
            intervention_type = INTERVENTION_TYPE_BY_SERVICE_CODE.get(service_code, "OTHER")
            status = intervention_statuses[(index // 4) % len(intervention_statuses)]
            intervention_date = today + timedelta(days=7 + index % 21) if status == "SCHEDULED" else today - timedelta(days=index % 365)
            interventions.append(
                Intervention(
                    farmer=farmer,
                    scope="INDIVIDUAL",
                    status=status,
                    service_request=linked_request,
                    intervention_type=intervention_type,
                    intervention_date=intervention_date,
                    description=f"{dict(Intervention.TYPE_CHOICES).get(intervention_type)} for registered farmer",
                    quantity=Decimal(1 + (index % 25)),
                    unit="kg" if intervention_type in {"SEEDS", "FERTILIZER"} else "service unit",
                    estimated_value=Decimal(500 + (index % 20) * 125),
                    funding_source="Municipal Agriculture Program",
                    provider="Office for Agricultural Services",
                    remarks=f"{SYNTHETIC_REMARKS_PREFIX} Synthetic intervention for workflow testing.",
                    recorded_by=staff,
                    is_active=index % 29 != 0,
                )
            )
        Intervention.objects.bulk_create(interventions, batch_size=500)
        InterventionRecipient.objects.bulk_create(
            [
                InterventionRecipient(
                    intervention=item,
                    farmer=item.farmer,
                    status="RECEIVED" if item.status == "COMPLETED" else "PENDING",
                    quantity_received=item.quantity if item.status == "COMPLETED" else None,
                    received_at=item.intervention_date if item.status == "COMPLETED" else None,
                )
                for item in interventions
            ],
            batch_size=500,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Replaced {replaced} prior synthetic farmers. Created {len(farmers)} farmers, "
                f"{len(parcels)} parcels, {len(crop_records)} commodities, "
                f"{len(service_requests)} service requests, and {len(interventions)} interventions."
            )
        )

