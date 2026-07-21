# ISO/IEC 25010 Verification Matrix

**Build assessed:** FMIS source updated July 20, 2026  
**Automated command:** `python manage.py test --settings=config.settings_test -v 2`  
**Deployment check:** `python manage.py check --deploy` using production-like environment values

| Quality characteristic | Test / expected result | Actual evidence | Status |
|---|---|---|---|
| Functional suitability | Public landing, login, Privacy Notice, and Terms pages return successfully | Automated legal/public-page test | Pass |
| Functional suitability | Valid credentials authenticate; invalid credentials do not | Automated authentication test | Pass |
| Functional suitability | Administrator and Staff access only their assigned modules | Automated role-boundary test | Pass |
| Functional suitability | Duplicate active government ID is rejected | Automated duplicate-ID form test | Pass |
| Functional suitability | Staff can create and view a service request | Automated end-to-end request test | Pass |
| Functional suitability | Invalid short service-request subject is rejected | Automated invalid-input test | Pass |
| Functional suitability | Commodity-per-parcel and Rosario filters return correct data | Automated filtered-report test | Pass |
| Functional suitability | CSV export contains filtered farmer data and remarks | Automated export test | Pass |
| Functional suitability | Report filters update the on-screen graph, matching-count table, and summary values from database records | Automated filtered graph/table test, including a no-results case | Pass |
| Functional suitability | Dashboard request trend and work-queue values reflect current service-request records | Automated database-backed dashboard graph test | Pass |
| Performance efficiency | Farmer Master List report uses a bounded number of database queries | Automated ceiling: no more than 5 queries | Pass |
| Performance efficiency | Dashboard, farmer list, and reports respond in under 2 seconds in the isolated test environment | Automated response-time test | Pass |
| Compatibility | Pages include responsive viewport configuration and breakpoint-based mobile CSS | Template/static inspection and system check | Pass (code) |
| Compatibility | Chrome desktop, Edge desktop, Firefox desktop, Android Chrome, and iOS Safari show no clipping or blocked actions | Use `BROWSER_DEVICE_TEST_RECORD.md` on the deployment target | Pending manual execution |
| Usability | Designated client and end user can use FMIS with favorable SUS results | Mean SUS 76.25 from two completed forms | Pass |
| Usability | Validation errors are associated with invalid fields and confirmations precede destructive actions | Form code and automated invalid-input tests | Pass |
| Reliability | A clean database applies all migrations without failure | Full isolated test-database build | Pass |
| Reliability | A portable compressed backup is created and immediately parsed | Automated backup test; verified `.json.gz` fixture | Pass |
| Reliability | Backup can be restored into a separate MySQL recovery database | Procedure in `BACKUP_AND_RECOVERY.md` | Pending deployment drill |
| Security | Password hashing, CSRF, protected routes, role checks, clickjacking protection, secure cookies, HSTS, and HTTPS redirect are configured | Django configuration and production deployment check | Pass |
| Security | Configured idle timeout ends an inactive authenticated session | Automated 15-minute timeout test | Pass |
| Security | Privacy Notice, Terms of Use, and registration consent are accessible | Automated page test and registration template | Pass |
| Security | Production refuses an unsafe or short secret key | Production settings guard and deployment check | Pass |
| Security | Google sign-in verifies a Google token and maps only to an existing active FMIS account | Code inspection; requires production Web client ID | Pass (code), credential pending |

## Automated result

The final isolated run discovered **16 tests**, applied all migrations, reported no framework issues, and completed successfully. Targeted filtered-report and dashboard-graph tests also passed against the configured MariaDB database. Manual browser/device checks, a MySQL recovery drill, production SMTP, Google OAuth configuration, and HTTPS certificate installation must be executed in the real deployment environment because they depend on external infrastructure.
