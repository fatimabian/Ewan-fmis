# FMIS Quality Verification Results

**Verification date:** September 16, 2026
**Test database:** Isolated in-memory SQLite database (no production/client records modified)

## Automated suite

- Tests discovered: **47**
- Tests passed: **47**
- Tests failed: **0**
- Final runtime: **7.889 seconds**
- Clean migration result: **Pass**
- Framework system check: **No issues**
- Migration drift check: **No changes detected**
- Verified backup test: **Pass**

Covered workflows include public/legal pages and shared branding, authentication, role separation, removal of legacy catalog/admin routes, the standardized request-type dropdown, the single farmer-type dropdown, idle timeout, validation, farmer and parcel workflows, record archiving and restoration, request cancellation history, protected supporting-document access, cumulative crop-area integrity, reports and exports, dashboard analytics, query ceilings, response time, audit resilience, and backup verification.

## Production security check

`python manage.py check --deploy` was run with `DEBUG=False`, a production-length secret, HTTPS origin, allowed host, secure-cookie/HSTS settings, and an isolated database. Result: **No issues**.

## MySQL / MariaDB status

The local MariaDB 10.4.32 database was reachable. Corrupt `mysql.db` and `mysql.proxies_priv` Aria system tables were preserved, repaired, and rechecked. Extended integrity checks passed for every FMIS and MariaDB system table. FMIS now uses a dedicated `fmis_app` account scoped to the `fmis` database instead of passwordless `root`. MariaDB 10.4 remains a local compatibility environment only; use a dedicated MariaDB 10.11 instance for production and complete the documented recovery drill before acceptance.

## Browser/device status

Local visual QA passed at 1440×900, 768×1024, and 390×844 for public, staff, administrator, registration, service-request, report, settings, recovery, and backup screens. No page-level horizontal overflow was detected. The signable Chrome/Edge/Firefox/Android/iOS deployment record remains pending in `BROWSER_DEVICE_TEST_RECORD.md`.

## Final recovery archive

The post-cleanup encrypted archive `backups/turnover-20260916/fmis-backup-20260916-112929.fmisbak` was independently authenticated and opened successfully. SHA-256: `11B0A0A4395B9BA70CAD72524D8091BD00E7DFBD61BFAE80E62F568C0A2F4930`.
