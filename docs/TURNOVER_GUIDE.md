# FMIS Turnover Guide

The latest local acceptance evidence is recorded in `TURNOVER_ACCEPTANCE_REPORT_2026-09-16.md`.

## Role ownership

The Administrator role is required for system governance. Administrators manage accounts and activation, review audit activity, download governance reports, and verify backups. The secure idle-session policy and Rosario localization are fixed system safeguards rather than routine administrator controls. Staff own operational farmer, parcel, crop, request, and agricultural-report workflows. Keeping these duties separate reduces accidental access to personal farmer data and makes accountability clearer.

The unused Django administration site and the former Service Catalog screens are not exposed. Standard agricultural request types are protected reference data installed by migration, and staff select them on the New Service Request form.

## Branding

The selected source is the third supplied logo: the orange-and-olive plant mark. The application copy is:

`static/images/brand/fmis-logo.png`

To change the brand later, replace that file with a transparent PNG using the same filename. Keep generous transparent padding and verify that the mark remains readable at 46×46 pixels. The shared path is used by the public landing page, authentication and recovery screens, legal pages, application sidebar, favicon, and printable farmer QR card.

## Release gate

Before a client signs acceptance:

1. Run `python manage.py test --settings=config.settings_test` and require zero failures.
2. Run `python manage.py makemigrations --check --dry-run` and require “No changes detected.”
3. Run `python manage.py check --deploy` with actual production environment values.
4. Complete `BROWSER_DEVICE_TEST_RECORD.md` on the deployed HTTPS candidate.
5. Complete and sign the separate-database MySQL recovery drill.
6. Verify SMTP password recovery, backup scheduling and off-site retention.
7. Record the deployed commit hash, database migration state, tester, date, and client acceptance decision.
8. Approve and sign `DATA_GOVERNANCE_AND_INCIDENT_POLICY.md`, including every pending retention decision.
9. Verify that the production web server denies direct public access to `media/farm_documents/`.
10. Include `THIRD_PARTY_NOTICES.md` and the pinned `requirements.txt` in the delivered source package.

The source can pass its automated gate independently, but production-dependent checklist items must not be marked complete until they are tested on the client deployment.
