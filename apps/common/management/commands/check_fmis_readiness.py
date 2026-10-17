import shutil
from pathlib import Path

from django.conf import settings
from django.core.mail import get_connection
from django.core.management import BaseCommand, CommandError
from django.db import connection

from apps.common.backups import _azure_blob_url, _dump_executable, _encryption_key


class Command(BaseCommand):
    help = "Validate production database, SMTP, logging, disk, and backup prerequisites."

    def handle(self, *args, **options):
        failures = []
        passed = []

        def check(label, action):
            try:
                action()
            except Exception as error:
                failures.append(f"{label}: {error}")
            else:
                passed.append(label)

        if settings.DEBUG:
            failures.append("Django production mode: DJANGO_DEBUG must be False")
        else:
            passed.append("Django production mode")
        if not getattr(settings, "FMIS_REQUIRE_MFA", False):
            failures.append("Multi-factor authentication: FMIS_REQUIRE_MFA must be True")
        else:
            passed.append("Multi-factor authentication")
        if "mysql" not in settings.DATABASES["default"]["ENGINE"]:
            failures.append("Database engine: production requires MySQL/MariaDB")
        else:
            passed.append("Database engine")

        check("Database connection", lambda: connection.ensure_connection())
        check("SMTP connection", self._open_email_connection)
        check("Backup encryption key", _encryption_key)
        check("MariaDB dump utility", _dump_executable)
        check("Azure backup URL", lambda: _azure_blob_url("readiness-test.fmisbak") or self._missing_azure())
        check("Application log directory", self._check_log_directory)
        check("Backup free disk space", self._check_backup_disk)

        if not settings.FMIS_BACKUP_SCHEDULER_CONFIGURED:
            failures.append(
                "Backup scheduler: run and verify the scheduled task, then set "
                "FMIS_BACKUP_SCHEDULER_CONFIGURED=True"
            )
        else:
            passed.append("Backup scheduler")

        for label in passed:
            self.stdout.write(self.style.SUCCESS(f"PASS  {label}"))
        if failures:
            for failure in failures:
                self.stderr.write(self.style.ERROR(f"FAIL  {failure}"))
            raise CommandError(f"FMIS is not deployment-ready ({len(failures)} failed check(s)).")
        self.stdout.write(self.style.SUCCESS("FMIS production readiness checks passed."))

    @staticmethod
    def _open_email_connection():
        email_connection = get_connection(fail_silently=False)
        try:
            if email_connection.open() is False:
                raise RuntimeError("SMTP server did not accept the connection")
        finally:
            email_connection.close()

    @staticmethod
    def _missing_azure():
        raise RuntimeError("BACKUP_AZURE_CONTAINER_URL is not configured")

    @staticmethod
    def _check_log_directory():
        log_root = Path(settings.LOG_ROOT)
        log_root.mkdir(parents=True, exist_ok=True)
        if not log_root.is_dir():
            raise RuntimeError("log directory is unavailable")

    @staticmethod
    def _check_backup_disk():
        backup_root = Path(settings.BACKUP_ROOT)
        existing_parent = backup_root
        while not existing_parent.exists() and existing_parent != existing_parent.parent:
            existing_parent = existing_parent.parent
        free_gb = shutil.disk_usage(existing_parent).free / (1024 ** 3)
        required_gb = float(getattr(settings, "FMIS_MIN_FREE_DISK_GB", 5))
        if free_gb < required_gb:
            raise RuntimeError(
                f"only {free_gb:.1f} GB free; at least {required_gb:.1f} GB is required"
            )
