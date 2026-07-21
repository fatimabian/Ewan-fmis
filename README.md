# FMIS

Farmer Management Information System for the Office of Agriculture, Rosario, Batangas.

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. In phpMyAdmin, import `database/fmis_database.sql`. It safely creates the `fmis` database when it does not exist and never deletes existing records.
4. Copy `.env.example` to `.env`, then set `MYSQL_USER` and `MYSQL_PASSWORD` to your local MySQL account. XAMPP commonly uses `root` with an empty password.
   If your XAMPP installation provides MariaDB 10.4, set `MYSQL_ALLOW_LEGACY_MARIADB=True`. Upgrade to MariaDB 10.5 or newer before deploying the system.
5. Run `python manage.py makemigrations authentication farmers farm_parcels crops service_catalog service_requests activity_logs`
6. Run `python manage.py migrate`
7. Run `python manage.py createsuperuser`
8. Run `python manage.py runserver`

Open `http://127.0.0.1:8000/` to view the public landing page, then choose **Sign In**. Superusers are automatically treated as Administrators.

## Optional sign-in services

- Google Sign-In requires a Google Identity Services Web OAuth client. Add its client ID to `GOOGLE_OAUTH_CLIENT_ID` in `.env`, allow `http://127.0.0.1:8000` and `http://localhost:8000` as JavaScript origins, and restart Django. Google access is limited to existing active FMIS accounts whose saved email matches the verified Google email.
- Forgot Password accepts either the email address or phone number saved on an active FMIS account and sends a secure reset link to that account's registered email. During local development, console-email reset links appear in the server terminal.
- The Google Identity Services flow uses the public Web client ID only. Never save the Google OAuth client secret in this project.

## Verification and production

- Run the isolated automated suite with `python manage.py test --settings=config.settings_test`.
- Run deployment checks with production environment values using `python manage.py check --deploy`.
- Use `.env.production.example` as the production checklist. It requires HTTPS, secure cookies, a unique secret, MySQL credentials, SMTP, and optional Google sign-in configuration.
- Create a verified backup with `python manage.py backup_fmis`; see `docs/BACKUP_AND_RECOVERY.md` for recovery drills.
- Privacy Notice and Terms of Use are available from the landing page, signed-in footer, and registration consent step.
