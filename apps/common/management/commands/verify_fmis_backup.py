from django.core.management import BaseCommand, CommandError

from apps.common.backups import verify_existing_backup


class Command(BaseCommand):
    help = "Authenticate and inspect an encrypted FMIS recovery archive without restoring production."

    def add_arguments(self, parser):
        parser.add_argument("backup_path")

    def handle(self, *args, **options):
        try:
            checksum = verify_existing_backup(options["backup_path"])
        except Exception as error:
            raise CommandError(f"Backup verification failed: {error}") from error
        self.stdout.write(self.style.SUCCESS(f"Backup is authentic and readable. SHA-256: {checksum}"))
