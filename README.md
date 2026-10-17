# FMIS

Farmer Management Information System for the Office of Agriculture, Rosario, Batangas.

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. In phpMyAdmin, import `database/fmis_database.sql`. It safely creates the `fmis` database when it does not exist and never deletes existing records.
4. Create a local `.env` file (Git ignores all `.env*` files), then set `DB_ENGINE=mysql`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, and `MYSQL_PORT` for your local MySQL account. XAMPP commonly uses `root` with an empty password for local development only.
   If your XAMPP installation provides MariaDB 10.4, set `MYSQL_ALLOW_LEGACY_MARIADB=True`. Upgrade to MariaDB 10.5 or newer before deploying the system.
5. Run `python manage.py migrate`. This also installs the protected standard agricultural request types.
6. Run `python manage.py createsuperuser`, then assign the Administrator role if required.
7. Run `python manage.py runserver`

Open `http://127.0.0.1:8000/` to view the public landing page, then choose **Sign In**. Superusers are automatically treated as Administrators.

## Roles and standard requests

- **Administrators** govern user access, audit activity, system reports, security settings, and backups. They do not encode operational farmer records.
- **Staff** register farmers and parcels, maintain crops, record service requests, and generate operational reports.
- Agricultural request types are installed as protected reference data by migration. Staff choose from the dropdown on the New Service Request screen; there is no separate Service Catalog administration page.

## Branding

The shared logo is `static/images/brand/fmis-logo.png`. Replace that file with another transparent PNG using the same filename to update the landing page, sign-in and recovery pages, sidebar, favicon, and printable farmer QR card. A restart or browser cache refresh may be needed.

## Account access

- Forgot Password accepts either the email address or phone number saved on an active FMIS account and sends a secure reset link to that account's registered email. During local development, console-email reset links appear in the server terminal.

## Verification and production

- Rebuild optimized frontend bundles after changing shared CSS with `python scripts/build_frontend_assets.py`; CI verifies that committed bundles are current with `python scripts/build_frontend_assets.py --check`.
- Run the isolated automated suite with `python manage.py test --settings=config.settings_test`.
- Every push and pull request runs the same tests, migration-drift detection, and production security checks through `.github/workflows/quality.yml`.
- Run deployment checks with production environment values using `python manage.py check --deploy`.
- Copy `deployment.env.example` to the server-only `.env`, then use `docs/PRODUCTION_DEPLOYMENT_CHECKLIST.md`. Production requires HTTPS, secure cookies, a unique secret, MySQL credentials, and SMTP.
- Create a verified backup with `python manage.py backup_fmis`; see `docs/BACKUP_AND_RECOVERY.md` for recovery drills.
- Use `docs/EMAIL_DELIVERY.md` to turn over an Office-owned sender mailbox and validate SMTP plus SPF/DKIM/DMARC before account activation is enabled in production.
- Privacy Notice and Terms of Use are available from the landing page, signed-in footer, and registration consent step.

Turnover and operations references are in `docs/TURNOVER_GUIDE.md`, `docs/PRODUCTION_HOSTING.md`, `docs/DATA_GOVERNANCE_AND_INCIDENT_POLICY.md`, `docs/BACKUP_AND_RECOVERY.md`, and `docs/THIRD_PARTY_NOTICES.md`.
