# FMIS Production Hosting Standard

FMIS must not be turned over while running through XAMPP's development stack or Django's `runserver` command.

## Required topology

1. A supported MariaDB/MySQL Windows service with automatic startup and a least-privilege `fmis_app` account.
2. Waitress bound to `127.0.0.1:8080` and installed as a restricted Windows service.
3. IIS or another approved reverse proxy providing the public HTTPS certificate, HTTP-to-HTTPS redirect, request-size limits, and security headers.
4. Static files served from `STATIC_ROOT`. Uploaded media must not expose `farm_documents/` as a public directory; supporting documents are served by the authenticated FMIS document endpoint.
5. Protected environment variables supplied to the service account, never committed to Git.

Install dependencies and collect static assets:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Start the application behind the HTTPS reverse proxy:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Run-FMISProduction.ps1
```

Before accepting traffic, run:

```powershell
python manage.py check --deploy
python manage.py test --settings=config.settings_test
python manage.py makemigrations --check --dry-run
```

All commands must succeed with the actual production environment. Configure the Windows service to restart after failure and write stdout/stderr to protected rotating logs. Database and application services must be verified after a server restart.
