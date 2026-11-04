"""Regression coverage for legacy backup names and retention of new recovery points."""
import base64
import os
import tempfile
import time
from pathlib import Path

from django.test import TestCase, override_settings

from apps.common.backups import create_verified_backup, prune_local_backups, verify_existing_backup


class BackupRetentionTests(TestCase):
    def test_new_dated_backup_survives_retention_with_legacy_filenames(self):
        with tempfile.TemporaryDirectory() as folder, override_settings(
            BACKUP_ROOT=Path(folder),
            FMIS_BACKUP_ENCRYPTION_KEY=base64.urlsafe_b64encode(b"r" * 32).decode(),
            BACKUP_AZURE_CONTAINER_URL="", BACKUP_RCLONE_REMOTE="",
        ):
            for index in range(9):
                path = Path(folder) / f"fmis-backup-20261104-1200{index:02}.fmisbak"
                path.write_bytes(b"legacy retention fixture")
                stamp = time.time() - 3600 - index * 60
                os.utime(path, (stamp, stamp))
            result = create_verified_backup()
            self.assertTrue(result.path.is_file())
            self.assertEqual(result.size_bytes, result.path.stat().st_size)
            self.assertEqual(verify_existing_backup(result.path), result.checksum)
            from apps.settings_page.models import BackupRun
            self.assertGreaterEqual(BackupRun.objects.latest("started_at").retained_copies, 1)

    def test_retention_chooses_newest_files_by_time_instead_of_name(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index in range(10):
                path = Path(folder) / f"fmis-backup-{index:02}.fmisbak"
                path.write_bytes(b"fixture")
                stamp = time.time() - index * 60
                os.utime(path, (stamp, stamp))
                paths.append(path)
            retained = prune_local_backups(Path(folder))
            self.assertTrue(all(path.exists() for path in paths[:7]))
            self.assertEqual(retained, len(list(Path(folder).glob("*.fmisbak"))))

    def test_current_verified_backup_is_protected_from_clock_skew(self):
        with tempfile.TemporaryDirectory() as folder:
            current = Path(folder) / "fmis-backup-current.fmisbak"
            current.write_bytes(b"current")
            for index in range(10):
                path = Path(folder) / f"fmis-backup-future-{index}.fmisbak"
                path.write_bytes(b"fixture")
                stamp = time.time() + 3600 + index
                os.utime(path, (stamp, stamp))
            prune_local_backups(Path(folder), protected=(current,))
            self.assertTrue(current.exists())
