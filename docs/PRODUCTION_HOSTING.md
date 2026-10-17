# FMIS Production Hosting Standard

FMIS must not be turned over while running through XAMPP's development stack or Django's `runserver` command.

## Required topology

1. A supported MariaDB/MySQL Windows service with automatic startup and a least-privilege `fmis_app` account.
2. Waitress bound to `127.0.0.1:8080` and installed as a restricted Windows service. The supplied launcher defaults to 32 worker threads, a 500-connection limit, and a 512-connection backlog based on the local 100-concurrent-user verification run.
3. IIS or another approved reverse proxy providing the public HTTPS certificate, HTTP-to-HTTPS redirect, request-size limits, and security headers.
4. Static files served from `STATIC_ROOT`. Uploaded media must not expose `farm_documents/`, `farmer_photos/`, `parcel_photos/`, or `account_profiles/` as public directories; those records are served by authenticated FMIS endpoints.
5. Protected environment variables supplied to the service account, never committed to Git.

For IIS, copy `deployment/iis/web.config.example` to the site root as
`web.config`, install URL Rewrite 2 and ARR, enable the ARR proxy, and confirm
that Waitress remains reachable only from `127.0.0.1`. The sample enforces the
HTTPS redirect, reverse-proxy forwarding, a 25 MiB outer request limit, and a
404 response for all four private media directories. Replace or extend it only
after repeating the private-media access tests.

Install dependencies and collect static assets:

```powershell
python -m pip install -r requirements.txt
python scripts/build_frontend_assets.py --check
python manage.py migrate
python manage.py collectstatic --noinput
```

Prepare a separate, Git-ignored production environment after local SMTP has
been tested:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Prepare-FMISProductionEnv.ps1
```

This creates `.env.production` with new production-only Django and backup
encryption secrets, copies the tested SMTP settings, and leaves explicit
`CHANGE_ME` values for the final hostname, database, release tag, and Azure
container. Complete those values on the server, protect the file with the
deployment service account, and install it as the server's `.env`. Do not use
`.env.production` for local `runserver` work.

Start the application behind the HTTPS reverse proxy:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Run-FMISProduction.ps1
```

The committed frontend bundles must pass the build check before deployment. WhiteNoise generates compressed, content-hashed static assets during `collectstatic`, allowing immutable one-year browser caching without serving stale files. The WSGI entry point performs one internal HTTPS landing-page readiness request before Waitress begins accepting traffic. Keep `FMIS_PREWARM_ON_START=True` unless startup diagnostics require temporarily disabling it. For unusually small or large servers, measure first and then override `-Threads`, `-ConnectionLimit`, and `-Backlog`; do not tune these values by guesswork.

Before accepting traffic, run:

```powershell
python manage.py check --deploy
python manage.py test --settings=config.settings_test
python manage.py makemigrations --check --dry-run
python manage.py check_fmis_readiness
```

All commands must succeed with the actual production environment. Configure the Windows service to restart after failure and write stdout/stderr to protected rotating logs. Database and application services must be verified after a server restart.

Install the local HTTPS availability check after the public URL works:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/Install-FMISHealthTask.ps1 -BaseUrl https://fmis.example.gov.ph/
```

This records failures in the Windows Application event log. Connect that log
to an external uptime/alerting provider with a municipal recipient; monitoring
from the same server alone cannot detect a server-wide or internet outage.

After the HTTPS proxy reports the application ready, run the repeatable read-only load check from a separate machine when possible:

```powershell
python scripts/Measure-FMISLoad.py https://fmis.example.gov.ph/ --requests 500 --workers 100
```

The default provisional gate matches the capstone testing worksheet: average response time at or below 2 seconds, P95 at or below 3 seconds, and error rate at or below 2 percent. Replace these defaults only with documented client-approved requirements.
