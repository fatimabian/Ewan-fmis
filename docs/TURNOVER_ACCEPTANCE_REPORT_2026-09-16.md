# FMIS Turnover Acceptance Report

**Verification date:** September 16, 2026  
**Candidate:** Local Rosario FMIS working copy  
**Decision:** Conditionally ready for client acceptance after the client-owned production dependencies below are completed

## Completed verification

- Repaired the corrupt MariaDB `mysql.db` and `mysql.proxies_priv` Aria tables after preserving their raw files.
- Passed extended integrity checks for every FMIS table and every MariaDB system table.
- Created a dedicated `fmis_app` database account limited to the `fmis` database; FMIS no longer connects as passwordless `root`.
- Replaced the placeholder Django secret and configured a unique backup-encryption key in the ignored `.env` file.
- Applied all database migrations, including retirement of the legacy `geh` sample service. Its three historical requests now use `Other Agricultural Concern`; the legacy row is inactive.
- Removed the temporary QA accounts, farmer, request, history, activity, and session records created during acceptance testing.
- Passed all **47 automated tests** using the isolated test settings.
- Passed Django system checks, the production deployment check with temporary validation values, migration-drift checks, and `git diff --check`.
- Verified administrator, staff, and public access paths in the local browser.
- Verified farmer registration steps, farmer Slip A editing/history, service-request creation, staff reports, administrator accounts, governance reports, password-reset request, logout, and backup status.
- Verified desktop (1440×900), tablet (768×1024), and mobile (390×844) layouts with no page-level horizontal overflow.

## Defects found and corrected during acceptance

1. Farmer registration rendered `Farm type` as free text even though the backend accepted only fixed choices. It is now a dropdown.
2. New crop registration exposed internal `is_active`, `archived_at`, and `archived_by` fields. They are no longer user-facing.
3. The reports statistics heading inherited the global 108-pixel application-header height. Its height is now content-sized; the measured heading-to-card gap is 8 pixels.
4. Legacy custom/sample services could still appear in the new-request dropdown. Only the protected canonical request list is now selectable.

## Final backup

- Archive: `backups/turnover-20260916/fmis-backup-20260916-112929.fmisbak`
- Format: authenticated encrypted FMIS recovery archive
- Size: 15,547 bytes
- SHA-256: `11B0A0A4395B9BA70CAD72524D8091BD00E7DFBD61BFAE80E62F568C0A2F4930`
- Independent verification: **Passed — authentic and readable**
- Supporting pre-upgrade dumps and preserved corrupt Aria files are in `backups/turnover-20260916/` and are excluded from Git.

The encryption key is stored in the protected local `.env`. Before turnover, an authorized officer must escrow that key separately from the application server. Without the key, encrypted recovery archives cannot be restored.

## Client-owned items still required

The following values cannot be invented or finalized by the developer:

- The approved production hostname, HTTPS certificate, and CSRF origin.
- The municipal SMTP server/account for real activation and password-recovery delivery.
- A private Azure Blob container/SAS credential, versioning, lifecycle policy, and immutable retention.
- The authorized Windows service account for the scheduled 2:00 AM backup task.
- The authoritative farmer, parcel, crop, account, and service-request dataset that will replace any remaining demonstration records.
- Signed retention, incident-response, recovery-drill, and client acceptance records.
- Real-device/browser sign-off on Chrome, Edge, Firefox, Android Chrome, and iOS Safari.

Do not remove or replace existing client-looking records until the Office supplies an approved data-cleanup list or import file.

## MariaDB disposition

The current shared XAMPP server is MariaDB 10.4.32 and contains multiple unrelated databases. Its corrupt Aria system tables were repaired and all current integrity checks pass, but MariaDB 10.4 remains unsuitable for final production use.

Do **not** replace the shared XAMPP binaries in place. The safe production path is:

1. Install a dedicated MariaDB 10.11 service or provision a separate production server.
2. Preserve the final FMIS backup and native SQL dump.
3. Restore `fmis` into the new instance.
4. Run `mariadb-upgrade`, restart the service, and inspect its error log.
5. Create the least-privilege `fmis_app` account on the new instance.
6. Run migrations, the full automated suite, application smoke tests, and a separate-database recovery drill.
7. Switch the protected production environment only after all checks pass.

This follows MariaDB's documented requirement to back up, cleanly stop the old server, upgrade binaries, run `mariadb-upgrade`, restart, and verify the application.

## Acceptance recommendation

The application code and local database are suitable for a supervised acceptance demonstration. Final production turnover should be signed only after the client-owned items and the dedicated MariaDB 10.11 migration are completed and recorded.
