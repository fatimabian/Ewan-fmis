# FMIS Backup and Recovery Procedure

## Daily verified backup

Run `python manage.py backup_fmis`. The command writes a timestamped `.json.gz` fixture to `FMIS_BACKUP_ROOT` and parses it immediately to verify that it is readable.

In production, schedule the command once per day using Windows Task Scheduler or the server's approved scheduler. Run it under the same virtual environment and service account as FMIS. Copy backups to encrypted storage outside the application server and retain them according to the Office's approved retention policy.

## Recovery drill

1. Stop application traffic and create a final backup when possible.
2. Restore to a separate test database first.
3. Run `python manage.py migrate` against the empty recovery database.
4. Run `python manage.py loaddata C:\path\to\fmis-backup-YYYYMMDD-HHMMSS.json.gz`.
5. Run `python manage.py check --deploy` and the automated test suite.
6. Verify administrator login, staff login, farmer records, parcels, commodities, service requests, reports, and audit logs.
7. Record the backup filename, start/end time, record counts, tester, and result in the ISO test matrix.

Never perform a recovery drill against the only production database. Restrict backup files because they contain personal information.
