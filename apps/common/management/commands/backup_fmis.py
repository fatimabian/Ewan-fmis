from django.core.management import BaseCommand

from apps.common.backups import create_verified_backup


class Command(BaseCommand):
    help = "Create a compressed, portable FMIS data backup and verify its JSON payload."

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", help="Directory for the backup; defaults to FMIS_BACKUP_ROOT.")
        parser.add_argument("--force", action="store_true", help="Create a manual backup even when scheduled backups are disabled.")

    def handle(self, *args, **options):
        from apps.settings_page.models import SystemSetting

        if not options.get("force") and not SystemSetting.load().automated_backups:
            self.stdout.write(self.style.WARNING("Scheduled backups are disabled in FMIS System Settings; no backup was created."))
            return
        backup = create_verified_backup(options.get("output_dir"))
        self.stdout.write(self.style.SUCCESS(f"Verified backup: {backup.path} ({backup.record_count} records)"))
