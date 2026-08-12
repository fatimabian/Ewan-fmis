# FMIS Backup and Recovery

## What the system protects

Each recovery point contains a native MariaDB SQL dump plus the complete private media directory, including uploaded farmer documents and images. FMIS packages these files, encrypts them with authenticated AES-256-GCM, verifies that the encrypted archive can be decrypted and opened, and then uploads it to private Azure Blob Storage when configured.

Ordinary FMIS users never handle SQL, JSON, encryption keys, or archive files. The administrator screen shows only the last backup time, status, storage, next scheduled run, retained copies, included files, and **Back Up Now**.

## Required protected configuration

Generate a unique encryption key on the deployment server:

```powershell
python manage.py generate_backup_key
```

Store the generated `FMIS_BACKUP_ENCRYPTION_KEY` in the protected `.env` file and in a separate offline recovery record controlled by the Office. A backup cannot be recovered if this key is lost. Never commit, email, or paste the key into FMIS.

Create a private Azure Blob container. Configure storage-account versioning, immutable retention, and lifecycle rules in Azure. Generate an HTTPS container SAS URL with only the required read, create, and write permissions, and store it as `BACKUP_AZURE_CONTAINER_URL` in `.env`. The SAS URL is a secret and must be rotated before expiry.

Configure the native database tool path, for example:

```env
MARIADB_DUMP_PATH=C:/Program Files/MariaDB 10.11/bin/mariadb-dump.exe
```

## Automatic daily backup

Run PowerShell as an authorized Windows deployment administrator:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Install-FMISBackupTask.ps1
```

The installer requests the protected Windows service-account credential and creates **FMIS Daily Encrypted Backup** at 2:00 AM. It uses the existing `backup_fmis` command, starts missed runs when the server becomes available, prevents overlapping jobs, and limits a run to two hours.

After the task completes successfully once, set:

```env
FMIS_BACKUP_SCHEDULER_CONFIGURED=True
```

Restart FMIS. The administrator screen will then report the automatic schedule accurately.

## Retention and immutability

FMIS rotates encrypted server copies using 7 daily, 4 weekly, and 12 monthly recovery points. Azure lifecycle management should independently enforce the same or stronger off-site retention. Azure versioning and immutable WORM retention must be enabled at the storage account/container; application code must not be able to weaken that policy.

## Verification and recovery drills

Every run decrypts and opens the archive before it is marked **Verified**. A technical administrator can independently authenticate a recovery point:

```powershell
python manage.py verify_fmis_backup C:\protected-backups\fmis-backup-YYYYMMDD-HHMMSS.fmisbak
```

At least quarterly, restore the native SQL dump into a separate, empty recovery database and restore media into an isolated directory. Never test restoration over the production database. Verify administrator login, staff login, farmers, parcels, commodities, service requests, reports, media, notifications, and audit history, then record the result and archive checksum.

## Security boundaries

- Only FMIS administrators may start a manual backup.
- The web screen never downloads the recovery archive to a user device.
- Database credentials are passed to the dump utility through a short-lived configuration file that is deleted immediately.
- Azure transport requires HTTPS and the uploaded size is verified with a separate storage request.
- Azure credentials and encryption keys remain outside source control.
- Backup errors shown to normal administrators do not expose database, Azure, or encryption secrets.
