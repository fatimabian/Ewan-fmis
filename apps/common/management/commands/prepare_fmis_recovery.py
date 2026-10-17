from django.core.management import BaseCommand, CommandError

from apps.common.backups import extract_verified_backup


class Command(BaseCommand):
    help = "Authenticate and extract an FMIS backup into an empty recovery-drill directory."

    def add_arguments(self, parser):
        parser.add_argument("backup_path")
        parser.add_argument("output_dir")

    def handle(self, *args, **options):
        try:
            destination, checksum = extract_verified_backup(
                options["backup_path"],
                options["output_dir"],
            )
        except Exception as error:
            raise CommandError(f"Recovery preparation failed: {error}") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Verified recovery files extracted to {destination}. SHA-256: {checksum}"
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "Restore database files only into a separate empty recovery database, never production."
            )
        )
