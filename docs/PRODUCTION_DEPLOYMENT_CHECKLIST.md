# Production Deployment Checklist

## Staff authentication readiness

- [ ] Keep `FMIS_REQUIRE_MFA=True` in the production environment.
- [ ] Ask every administrator and staff member to install a compatible authenticator app on their own phone before first production sign-in.
- [ ] Have each staff member privately store the ten one-time recovery codes shown after enrollment.
- [ ] Enroll at least two administrator accounts so one administrator can reset the other's MFA after identity confirmation.

Existing active accounts are guided through authenticator enrollment after their next successful password login. Newly created accounts complete email activation first, then authenticator enrollment.

- [ ] Run `scripts/Prepare-FMISProductionEnv.ps1`, replace every `CHANGE_ME` value in `.env.production`, install it as a protected server-only `.env`, and confirm Git ignores both files.
- [ ] Generate a unique secret key of at least 50 characters.
- [ ] Set `DJANGO_DEBUG=False`, the real hostname, and the HTTPS CSRF origin.
- [ ] Create a least-privilege MySQL application user and run `python manage.py migrate`.
- [ ] Configure a trusted TLS certificate and redirect all HTTP traffic to HTTPS.
- [ ] Install IIS URL Rewrite and ARR, enable proxying, deploy `deployment/iis/web.config.example` as `web.config`, and verify Waitress is bound only to `127.0.0.1:8080`.
- [ ] Configure SMTP and test password recovery by both saved email and saved phone identifier.
- [ ] Transfer the Office-owned FMIS mailbox, MFA recovery, SMTP credential, and DNS administration to authorized municipal personnel; follow `EMAIL_DELIVERY.md`.
- [ ] Run `python manage.py collectstatic` and serve static assets using the approved web server.
- [ ] Keep `farm_documents/`, `farmer_photos/`, and `parcel_photos/` blocked from direct web-server access; these records must only use the authenticated Django endpoints.
- [x] Account profile photos use an authenticated, private endpoint. Block direct web-server access to `account_profiles/` alongside the other protected media directories.
- [ ] Generate and escrow the FMIS backup encryption key outside the application server.
- [ ] Configure a private Azure Blob container with HTTPS SAS access, versioning, lifecycle retention, and immutable WORM protection.
- [ ] Install `scripts/Install-FMISBackupTask.ps1`, verify one 2:00 AM run, then set `FMIS_BACKUP_SCHEDULER_CONFIGURED=True`.
- [ ] Perform and sign a separate-database recovery drill.
- [ ] Run `python manage.py check --deploy` and `python manage.py test --settings=config.settings_test`.
- [ ] Run `python -m pip check` and `python scripts/build_frontend_assets.py --check`.
- [ ] Run `python scripts/Measure-FMISLoad.py https://your-production-host/ --requests 500 --workers 100` from another machine and meet the documented latency/error thresholds.
- [ ] Test first-time account activation and password recovery against the real SMTP service; confirm messages do not land in spam and that expired/incorrect codes are rejected.
- [ ] Verify SPF, DKIM, and DMARC for the production sender domain.
- [ ] Add uptime monitoring, protected rotating application/proxy logs, and an alert recipient owned by the municipality.
- [ ] Point the uptime monitor to `/health/`; alert on any non-200 response. Do not expose server diagnostics through this endpoint.
- [ ] Install `scripts/Install-FMISHealthTask.ps1` on the server and connect its Windows Application log failures to the municipal alerting service.
- [ ] Run `python manage.py check_fmis_readiness` using the real production environment and resolve every failed check.
- [ ] Complete `BROWSER_DEVICE_TEST_RECORD.md` on Chrome, Edge, Firefox, Android Chrome, and iOS Safari.
- [ ] Keep the unredacted evaluation forms in restricted storage; use redacted copies for public presentation.

External credentials and certificates are intentionally not stored in source control.
