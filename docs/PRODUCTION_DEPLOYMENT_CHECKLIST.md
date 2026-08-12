# Production Deployment Checklist

- [ ] Copy `.env.production.example` to the server's protected environment file.
- [ ] Generate a unique secret key of at least 50 characters.
- [ ] Set `DJANGO_DEBUG=False`, the real hostname, and the HTTPS CSRF origin.
- [ ] Create a least-privilege MySQL application user and run `python manage.py migrate`.
- [ ] Configure a trusted TLS certificate and redirect all HTTP traffic to HTTPS.
- [ ] Configure SMTP and test password recovery by both saved email and saved phone identifier.
- [ ] Configure the Google Identity Services Web client ID and authorized HTTPS origin, if Google sign-in is retained.
- [ ] Run `python manage.py collectstatic` and serve static/media files using the approved web server.
- [ ] Generate and escrow the FMIS backup encryption key outside the application server.
- [ ] Configure a private Azure Blob container with HTTPS SAS access, versioning, lifecycle retention, and immutable WORM protection.
- [ ] Install `scripts/Install-FMISBackupTask.ps1`, verify one 2:00 AM run, then set `FMIS_BACKUP_SCHEDULER_CONFIGURED=True`.
- [ ] Perform and sign a separate-database recovery drill.
- [ ] Run `python manage.py check --deploy` and `python manage.py test --settings=config.settings_test`.
- [ ] Complete `BROWSER_DEVICE_TEST_RECORD.md` on Chrome, Edge, Firefox, Android Chrome, and iOS Safari.
- [ ] Keep the unredacted evaluation forms in restricted storage; use redacted copies for public presentation.

External credentials and certificates are intentionally not stored in source control.
