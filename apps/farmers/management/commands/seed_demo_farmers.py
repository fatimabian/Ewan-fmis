from datetime import date

from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.common.constants import ROSARIO_BARANGAYS
from apps.farmers.models import Farmer


DEMO_RSBSA_PREFIX = "DEMO-RSBSA-"
DEMO_REMARKS_PREFIX = "FMIS-DEMO-DATA:"


class Command(BaseCommand):
    help = "Create clearly marked dummy farmers for FMIS demonstrations and load testing."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=4700)

    @transaction.atomic
    def handle(self, *args, **options):
        count = options["count"]
        if count < 1 or count > 50000:
            raise CommandError("--count must be between 1 and 50000.")

        existing = set(
            Farmer.objects.filter(rsbsa_number__startswith=DEMO_RSBSA_PREFIX)
            .values_list("rsbsa_number", flat=True)
        )
        now = timezone.now()
        education = ("Elementary", "High School", "College", "Vocational")
        records = []
        for index in range(1, count + 1):
            rsbsa_number = f"{DEMO_RSBSA_PREFIX}{index:06d}"
            if rsbsa_number in existing:
                continue
            records.append(
                Farmer(
                    first_name=f"Demo{index:04d}",
                    middle_name="Sample",
                    last_name=f"Farmer{index:04d}",
                    sex="MALE" if index % 2 else "FEMALE",
                    birth_date=date(
                        1955 + (index % 45),
                        1 + (index % 12),
                        1 + (index % 27),
                    ),
                    place_of_birth="Rosario, Batangas",
                    house_lot_purok=f"Demo Purok {1 + (index % 7)}",
                    barangay=ROSARIO_BARANGAYS[(index - 1) % len(ROSARIO_BARANGAYS)],
                    phone_number=f"0999{index:07d}",
                    email=f"demo.farmer.{index:04d}@example.invalid",
                    civil_status="MARRIED" if index % 3 else "SINGLE",
                    highest_education=education[index % len(education)],
                    religion="Demo record",
                    livelihood="FARMER",
                    activities="FARMER_CROPS",
                    remarks=(
                        f"{DEMO_REMARKS_PREFIX} Dummy farmer {index} of {count}. "
                        "Safe to remove with delete_demo_farmers."
                    ),
                    rsbsa_number=rsbsa_number,
                    registration_status="COMPLETED",
                    consent_given=True,
                    submitted_at=now,
                    is_active=True,
                )
            )

        Farmer.objects.bulk_create(records, batch_size=500)
        total = Farmer.objects.filter(rsbsa_number__startswith=DEMO_RSBSA_PREFIX).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(records)} dummy farmers; {total} demo farmers are now available."
            )
        )

