# FMIS Production Hosting Standard

FMIS must not be turned over while running through XAMPP's development stack or Django's `runserver` command.

## Required topology

1. A supported MariaDB/MySQL Windows service with automatic startup and a least-privilege `fmis_app` account.
2. Waitress bound to `127.0.0.1:8080` and installed as a restricted Windows service. The supplied launcher defaults to 32 worker threads, a 500-connection limit, and a 512-connection backlog based on the local 100-concurrent-user verification run.
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

The WSGI entry point performs one internal HTTPS landing-page readiness request before Waitress begins accepting traffic. Keep `FMIS_PREWARM_ON_START=True` unless startup diagnostics require temporarily disabling it. For unusually small or large servers, measure first and then override `-Threads`, `-ConnectionLimit`, and `-Backlog`; do not tune these values by guesswork.

Before accepting traffic, run:

```powershell
python manage.py check --deploy
python manage.py test --settings=config.settings_test
python manage.py makemigrations --check --dry-run
```

All commands must succeed with the actual production environment. Configure the Windows service to restart after failure and write stdout/stderr to protected rotating logs. Database and application services must be verified after a server restart.

After the HTTPS proxy reports the application ready, run the repeatable read-only load check from a separate machine when possible:

```powershell
python scripts/Measure-FMISLoad.py https://fmis.example.gov.ph/ --requests 500 --workers 100
```

The default provisional gate matches the capstone testing worksheet: average response time at or below 2 seconds, P95 at or below 3 seconds, and error rate at or below 2 percent. Replace these defaults only with documented client-approved requirements.
