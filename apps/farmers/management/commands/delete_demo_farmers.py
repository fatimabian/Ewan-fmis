from django.core.management import BaseCommand, CommandError
from django.db import transaction

from apps.farmers.demo_data import delete_synthetic_data


CONFIRMATION = "DELETE-DEMO-FARMERS"


class Command(BaseCommand):
    help = "Remove only synthetic FMIS farmers and their linked test records."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", default="")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["confirm"] != CONFIRMATION:
            raise CommandError(f"Pass --confirm {CONFIRMATION} to remove synthetic data.")

        deleted_count = delete_synthetic_data()
        if not deleted_count:
            self.stdout.write(self.style.WARNING("No marked synthetic farmers were found."))
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_count} marked synthetic farmers and their linked test records."
            )
        )
