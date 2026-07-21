import gzip
import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone


@dataclass(frozen=True)
class VerifiedBackup:
    path: Path
    record_count: int


def create_verified_backup(output_dir=None):
    """Export FMIS data, compress it, and verify that the fixture is readable."""
    destination_dir = Path(output_dir or settings.BACKUP_ROOT).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"fmis-backup-{timezone.localtime():%Y%m%d-%H%M%S}.json.gz"

    with gzip.open(destination, "wt", encoding="utf-8") as output:
        call_command(
            "dumpdata",
            exclude=["contenttypes", "auth.permission", "admin.logentry", "sessions"],
            indent=2,
            stdout=output,
        )

    try:
        with gzip.open(destination, "rt", encoding="utf-8") as backup_file:
            records = json.load(backup_file)
        if not isinstance(records, list):
            raise ValueError("The export is not a Django fixture list.")
    except (OSError, ValueError, json.JSONDecodeError):
        destination.unlink(missing_ok=True)
        raise RuntimeError("Backup verification failed; the incomplete backup was removed.")

    return VerifiedBackup(path=destination, record_count=len(records))
