from django.core.management import BaseCommand, CommandError
from django.db import transaction

from apps.farmers.management.commands.seed_demo_farmers import (
    DEMO_REMARKS_PREFIX,
    DEMO_RSBSA_PREFIX,
)
from apps.farmers.models import Farmer
from apps.interventions.models import Intervention, InterventionRecipient
from apps.service_requests.models import ServiceRequest


CONFIRMATION = "DELETE-DEMO-FARMERS"


class Command(BaseCommand):
    help = "Remove only farmers created by seed_demo_farmers and their linked test records."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"Pass --confirm {CONFIRMATION} to remove demo data.")

        dummy_farmers = Farmer.objects.filter(
            rsbsa_number__startswith=DEMO_RSBSA_PREFIX,
            remarks__startswith=DEMO_REMARKS_PREFIX,
        )
        dummy_ids = list(dummy_farmers.values_list("pk", flat=True))
        if not dummy_ids:
            self.stdout.write(self.style.WARNING("No marked demo farmers were found."))
            return

        # Remove protected operational links first. Group interventions that also
        # contain real farmers are preserved; only their dummy recipients are removed.
        Intervention.objects.filter(farmer_id__in=dummy_ids).delete()
        InterventionRecipient.objects.filter(farmer_id__in=dummy_ids).delete()
        ServiceRequest.objects.filter(farmer_id__in=dummy_ids).delete()
        deleted_count = len(dummy_ids)
        dummy_farmers.delete()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted_count} marked dummy farmers and their test links.")
        )

