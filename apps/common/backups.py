import base64
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone


BACKUP_MAGIC = b"FMISBACKUP1"
NONCE_BYTES = 12
TAG_BYTES = 16
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class VerifiedBackup:
    path: Path
    archive_name: str
    size_bytes: int
    checksum: str
    storage_label: str
    offsite: bool
    media_files: int
    database_format: str

    @property
    def record_count(self):
        """Compatibility alias for older callers; native dumps do not expose a row count."""
        return 0


def _encryption_key():
    encoded = getattr(settings, "FMIS_BACKUP_ENCRYPTION_KEY", "").strip()
    if not encoded:
        raise RuntimeError(
            "Backup encryption is not configured. Add FMIS_BACKUP_ENCRYPTION_KEY to the protected environment."
        )
    try:
        key = base64.urlsafe_b64decode(encoded.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("FMIS_BACKUP_ENCRYPTION_KEY is not valid URL-safe base64.") from error
    if len(key) != 32:
        raise RuntimeError("FMIS_BACKUP_ENCRYPTION_KEY must decode to exactly 32 bytes.")
    return key


def _dump_executable():
    configured = getattr(settings, "MARIADB_DUMP_PATH", "").strip()
    candidates = [
        configured,
        shutil.which("mariadb-dump"),
        shutil.which("mysqldump"),
        r"C:\xampp\mysql\bin\mysqldump.exe",
        r"C:\Program Files\MariaDB 10.4\bin\mariadb-dump.exe",
        r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("MariaDB backup utility was not found. Configure MARIADB_DUMP_PATH.")


def _create_database_dump(work_dir):
    database = settings.DATABASES["default"]
    engine = database.get("ENGINE", "")
    if "mysql" not in engine:
        destination = work_dir / "database.json"
        with destination.open("w", encoding="utf-8") as output:
            call_command(
                "dumpdata",
                exclude=["contenttypes", "auth.permission", "admin.logentry", "sessions"],
                stdout=output,
            )
        return destination, "portable-test-fixture"

    destination = work_dir / "database.sql"
    client_file = work_dir / "database-client.cnf"
    client_file.write_text(
        "[client]\n"
        f"user={database.get('USER', '')}\n"
        f"password={database.get('PASSWORD', '')}\n"
        f"host={database.get('HOST') or '127.0.0.1'}\n"
        f"port={database.get('PORT') or '3306'}\n"
        "default-character-set=utf8mb4\n",
        encoding="utf-8",
    )
    try:
        command = [
            str(_dump_executable()),
            f"--defaults-extra-file={client_file}",
            "--single-transaction",
            "--quick",
            "--routines",
            "--events",
            "--triggers",
            "--hex-blob",
            f"--result-file={destination}",
            str(database["NAME"]),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if result.returncode:
            message = (result.stderr or result.stdout or "Unknown database dump error").strip()
            raise RuntimeError(f"MariaDB backup failed: {message[:300]}")
    finally:
        client_file.unlink(missing_ok=True)
    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError("MariaDB backup produced an empty database file.")
    return destination, "mariadb-native-sql"


def _build_archive(work_dir, database_dump, database_format):
    media_root = Path(settings.MEDIA_ROOT)
    media_files = sum(1 for path in media_root.rglob("*") if path.is_file()) if media_root.exists() else 0
    manifest = {
        "format": "FMIS encrypted recovery archive",
        "version": 1,
        "created_at": timezone.now().isoformat(),
        "database_format": database_format,
        "database_file": database_dump.name,
        "media_files": media_files,
    }
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive_path = work_dir / "recovery.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(database_dump, arcname=f"database/{database_dump.name}")
        archive.add(manifest_path, arcname="manifest.json")
        if media_root.exists():
            archive.add(media_root, arcname="media")
    return archive_path, media_files


def _encrypt_archive(source, destination, key):
    nonce = os.urandom(NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    with source.open("rb") as source_file, destination.open("wb") as encrypted_file:
        encrypted_file.write(BACKUP_MAGIC)
        encrypted_file.write(nonce)
        while chunk := source_file.read(CHUNK_SIZE):
            encrypted_file.write(encryptor.update(chunk))
        encrypted_file.write(encryptor.finalize())
        encrypted_file.write(encryptor.tag)


def _verify_encrypted_archive(path, key):
    size = path.stat().st_size
    minimum_size = len(BACKUP_MAGIC) + NONCE_BYTES + TAG_BYTES + 1
    if size < minimum_size:
        raise RuntimeError("Encrypted backup is incomplete.")
    with path.open("rb") as encrypted_file:
        if encrypted_file.read(len(BACKUP_MAGIC)) != BACKUP_MAGIC:
            raise RuntimeError("Encrypted backup header is invalid.")
        nonce = encrypted_file.read(NONCE_BYTES)
        encrypted_file.seek(-TAG_BYTES, os.SEEK_END)
        tag = encrypted_file.read(TAG_BYTES)
        ciphertext_size = size - len(BACKUP_MAGIC) - NONCE_BYTES - TAG_BYTES
        encrypted_file.seek(len(BACKUP_MAGIC) + NONCE_BYTES)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        remaining = ciphertext_size
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as verified_file:
            verified_path = Path(verified_file.name)
            try:
                while remaining:
                    chunk = encrypted_file.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise RuntimeError("Encrypted backup ended unexpectedly.")
                    remaining -= len(chunk)
                    verified_file.write(decryptor.update(chunk))
                verified_file.write(decryptor.finalize())
            except Exception:
                verified_path.unlink(missing_ok=True)
                raise RuntimeError("Encrypted backup authentication failed.")
    try:
        with tarfile.open(verified_path, "r:gz") as archive:
            names = set(archive.getnames())
            if "manifest.json" not in names or not any(name.startswith("database/") for name in names):
                raise RuntimeError("Recovery archive is missing required database or manifest files.")
    finally:
        verified_path.unlink(missing_ok=True)


def _azure_blob_url(filename):
    container_url = getattr(settings, "BACKUP_AZURE_CONTAINER_URL", "").strip()
    if not container_url:
        return ""
    parsed = urlsplit(container_url)
    if parsed.scheme != "https" or not parsed.netloc or not parsed.query:
        raise RuntimeError("BACKUP_AZURE_CONTAINER_URL must be an HTTPS container SAS URL.")
    path = f"{parsed.path.rstrip('/')}/{quote(filename)}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def _upload_and_verify(path, checksum):
    blob_url = _azure_blob_url(path.name)
    if not blob_url:
        return False
    try:
        with path.open("rb") as backup_file:
            response = requests.put(
                blob_url,
                data=backup_file,
                headers={
                    "x-ms-blob-type": "BlockBlob",
                    "x-ms-version": "2023-11-03",
                    "x-ms-meta-sha256": checksum,
                    "Content-Type": "application/octet-stream",
                },
                timeout=(20, 1800),
            )
    except requests.RequestException as error:
        raise RuntimeError("Secure off-site storage could not be reached.") from error
    if response.status_code not in (201, 202):
        raise RuntimeError(f"Off-site upload failed with storage status {response.status_code}.")
    try:
        verification = requests.head(
            blob_url,
            headers={"x-ms-version": "2023-11-03"},
            timeout=(20, 60),
        )
    except requests.RequestException as error:
        raise RuntimeError("Secure off-site backup verification could not be completed.") from error
    if verification.status_code != 200:
        raise RuntimeError("Off-site backup upload could not be verified.")
    if int(verification.headers.get("Content-Length", "-1")) != path.stat().st_size:
        raise RuntimeError("Off-site backup size did not match the verified local archive.")
    return True


def prune_local_backups(destination_dir):
    """Retain 7 daily, 4 weekly, and 12 monthly encrypted recovery points."""
    backups = sorted(destination_dir.glob("fmis-backup-*.fmisbak"), reverse=True)
    keep = set(backups[:7])
    weekly = {}
    monthly = {}
    for path in backups:
        modified = timezone.datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.get_current_timezone())
        weekly.setdefault(modified.strftime("%G-%V"), path)
        monthly.setdefault(modified.strftime("%Y-%m"), path)
    keep.update(list(weekly.values())[:4])
    keep.update(list(monthly.values())[:12])
    for path in backups:
        if path not in keep:
            path.unlink(missing_ok=True)
    return len(keep)


def _file_checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        while chunk := backup_file.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def verify_existing_backup(path):
    path = Path(path).expanduser().resolve()
    _verify_encrypted_archive(path, _encryption_key())
    return _file_checksum(path)


def create_verified_backup(output_dir=None):
    """Create, encrypt, verify, optionally upload, and retain an FMIS recovery archive."""
    from apps.settings_page.models import BackupRun

    destination_dir = Path(output_dir or settings.BACKUP_ROOT).expanduser().resolve()
    destination_dir.mkdir(parents=True, exist_ok=True)
    run = BackupRun.objects.create(status="RUNNING", storage="Preparing encrypted backup")
    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M%S")
    destination = destination_dir / f"fmis-backup-{timestamp}.fmisbak"
    try:
        key = _encryption_key()
        with tempfile.TemporaryDirectory(prefix="fmis-backup-") as temp_dir:
            work_dir = Path(temp_dir)
            database_dump, database_format = _create_database_dump(work_dir)
            archive_path, media_files = _build_archive(work_dir, database_dump, database_format)
            _encrypt_archive(archive_path, destination, key)
        _verify_encrypted_archive(destination, key)
        checksum = _file_checksum(destination)
        offsite = _upload_and_verify(destination, checksum)
        retained = prune_local_backups(destination_dir)
        storage_label = "Secure off-site storage" if offsite else "Encrypted server storage"
        run.status = "VERIFIED"
        run.storage = storage_label
        run.archive_name = destination.name
        run.size_bytes = destination.stat().st_size
        run.checksum = checksum
        run.offsite = offsite
        run.media_files = media_files
        run.retained_copies = retained
        run.completed_at = timezone.now()
        run.save()
        return VerifiedBackup(
            path=destination,
            archive_name=destination.name,
            size_bytes=destination.stat().st_size,
            checksum=checksum,
            storage_label=storage_label,
            offsite=offsite,
            media_files=media_files,
            database_format=database_format,
        )
    except Exception as error:
        destination.unlink(missing_ok=True)
        run.status = "FAILED"
        run.error_message = str(error)[:500]
        run.completed_at = timezone.now()
        run.save(update_fields=("status", "error_message", "completed_at"))
        raise
