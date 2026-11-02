from django.core.management.base import BaseCommand

from apps.form_scan.services import expire_stale_scans


class Command(BaseCommand):
    help = "Clear scans left unfinished past the retention time and delete the photos of every finished scan."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, help="Override OCR_RETENTION_HOURS for this run.")

    def handle(self, *args, **options):
        cleared = expire_stale_scans(options["hours"])
        self.stdout.write(self.style.SUCCESS(f"Cleared {cleared} unfinished scan(s); photos deleted."))
