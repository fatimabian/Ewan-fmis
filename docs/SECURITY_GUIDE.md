# FMIS Security Guide

This is the maintenance map for FMIS security controls. It explains where to review a control when requirements or deployment conditions change. It is not a promise that attacks are impossible; security also depends on the server, database, network, staff practices, backups, and timely dependency updates.

## Where to check each security control

| Security area | Primary files to inspect |
|---|---|
| Production secrets, HTTPS, cookies, allowed hosts, database requirements | `config/settings.py`, `.env.production.example` |
| Global browser security headers (CSP, permissions, anti-framing) | `apps/common/middleware.py` (`SecurityHeadersMiddleware`), `config/settings.py` (`MIDDLEWARE`) |
| URL exposure and development media handling | `config/urls.py`, each app's `urls.py` |
| Login throttling, session expiry, remembered login | `apps/authentication/views.py`, `apps/common/middleware.py` |
| Password rules and reset links | `config/settings.py` (`AUTH_PASSWORD_VALIDATORS`), `apps/authentication/forms.py`, `apps/authentication/urls.py` |
| First-time email activation and OTP limits | `apps/authentication/activation.py`, `apps/authentication/views.py` |
| Roles and authorization | `apps/common/permissions.py`, `apps/common/mixins.py`, every app's `views.py` |
| Account administration safeguards | `apps/accounts/views.py`, `apps/accounts/forms.py` |
| CSRF protection | `config/settings.py` middleware and every state-changing HTML `<form>` (must contain `{% csrf_token %}`) |
| Input and business validation | `apps/common/forms.py` and each app's `forms.py` |
| Sensitive document validation and authenticated delivery | `apps/farmers/forms.py` (`DocumentRegistrationForm`), `apps/farmers/views.py` (`FarmerDocumentDownloadView`), `config/urls.py` |
| Parcel photo validation | `apps/common/forms.py` (`MultipleImageField`), `apps/farm_parcels/forms.py` |
| Report authorization and CSV/PDF safety | `apps/reports/views.py`, `apps/reports/export.py` |
| Notification ownership and safe redirects | `apps/notifications/views.py`, `apps/notifications/services.py` |
| Audit records and security-event notifications | `apps/activity_logs/`, `apps/notifications/` |
| Encrypted backup, verification, retention, off-site copy | `apps/common/backups.py`, `apps/settings_page/views.py`, `docs/BACKUP_AND_RECOVERY.md` |
| Security regression tests | `apps/common/tests.py`, app-specific `tests.py` files |

## Attack classes reviewed

| Attack or failure | FMIS control / status |
|---|---|
| SQL injection | Django ORM is used; no application raw SQL was found. Keep filters in ORM expressions. |
| Stored/reflected XSS | Django auto-escaping plus a global Content Security Policy. Avoid adding `|safe`, `mark_safe`, or untrusted inline HTML. The account help-text use is developer-authored, not user data. |
| CSRF | Django CSRF middleware is enabled. All writes must remain POST requests with CSRF tokens. |
| Broken access control / IDOR | Login and role mixins protect operational views; object downloads also verify the authorized role. New views must inherit the correct mixins. |
| Brute-force login and email flooding | Login, password recovery, OTP attempts, and OTP resend are throttled. For multiple web-server processes, use a shared production cache so limits are shared across processes. |
| Session theft/fixation | HttpOnly/SameSite cookies, login rotation through Django, idle timeout, fixed remembered-login expiry, and Secure cookies in production. HTTPS is mandatory in production. |
| Clickjacking | `X_FRAME_OPTIONS = "DENY"` and CSP `frame-ancestors 'none'`. |
| Open redirect | Django validates login `next`; notification destinations are restricted to the current host. |
| Malicious upload / unrestricted file upload | Size, extension, and file-signature/image validation are applied. Farmer documents are delivered through an authenticated view; direct development access to `media/farm_documents/` is denied. Production web-server rules must also deny that folder. Antivirus scanning is still recommended for production uploads. |
| CSV/formula injection | CSV export cells beginning with spreadsheet formula markers are escaped. |
| Path traversal | Application file access uses Django storage/model references rather than user-provided filesystem paths. Backup destinations are server configuration, not web input. |
| Command injection | Database backup uses a fixed argument list with `shell=False`; no application shell execution from user input was found. |
| Sensitive-data caching | Authenticated responses are marked private and no-store. |
| Secret leakage | `.env`, databases, uploads, and backups are ignored by Git. Never commit real environment files or SAS URLs. Rotate any secret that has been shared. |
| Weak backup confidentiality | Backups use authenticated AES-GCM encryption, integrity verification, retention, and optional HTTPS off-site storage. Store the encryption key separately from backups. |
| Dependency vulnerabilities | Versions are pinned in `requirements.txt`; run a dependency vulnerability scanner before every release and update promptly. |
| Denial of service | Request/upload size limits exist at form level. Add reverse-proxy body-size, connection, and rate limits for production; application checks alone are not enough. |

## Farmer QR access in the field

- Set `FMIS_FIELD_BASE_URL` to the stable HTTPS FMIS address reachable by AEW devices, for example `https://fmis.rosario.gov.ph` or an HTTPS VPN address.
- Add that hostname to `DJANGO_ALLOWED_HOSTS` and its full origin to `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Generate or reprint farmer QR sheets only after the field URL is configured. A QR printed while the application uses `127.0.0.1` or `localhost` cannot work on another device.
- The QR contains a signed record locator, not permission to view data. The AEW must still sign in with an active Staff account.
- Do not expose the development server directly to the internet. Use a production application server, HTTPS reverse proxy, firewall or VPN, backups, and monitoring.
- Live field lookup requires connectivity. Offline access is not currently implemented; adding it requires encrypted device storage, expiry, remote revocation, and conflict-safe synchronization.

## Required production checks

1. Copy `.env.production.example` to a protected server-only environment and replace every placeholder. Never use the development key, root database account, or an empty database password.
2. Set `DJANGO_DEBUG=False`, a unique 50+ character `DJANGO_SECRET_KEY`, exact `DJANGO_ALLOWED_HOSTS`, and exact HTTPS `DJANGO_CSRF_TRUSTED_ORIGINS`.
3. Terminate TLS with a valid certificate. Keep secure cookies, HTTPS redirect, and HSTS enabled. Set `DJANGO_BEHIND_HTTPS_PROXY=True` only when the trusted proxy correctly sets `X-Forwarded-Proto` and strips client-supplied copies.
4. Use a least-privilege MariaDB account restricted to the FMIS database and host. Do not expose MariaDB port 3307 to the public network.
5. Configure the production web server to **deny direct requests to `/media/farm_documents/`**. Documents must only be served through `/farmers/documents/<id>/` after authentication.
6. Put FMIS behind a reverse proxy/firewall with request-size limits, connection limits, request-rate limits, access logs, and IP restrictions where appropriate.
7. Configure SMTP, encrypted backups, off-site storage, scheduled backups, restore drills, log monitoring, and operating-system patching.
8. Use a shared cache (Redis or Memcached) if more than one application process/server is deployed, so login and recovery throttles are not per-process.
9. Run before release: `python manage.py check --deploy`, `python manage.py makemigrations --check`, and the complete test suite using production-equivalent settings.
10. Run authenticated role tests with separate Administrator and Staff accounts. Confirm a staff account cannot access administrator pages, and an administrator cannot enter staff-only operational pages.

## Remaining operational risks

- CSP currently permits inline scripts/styles because existing templates contain inline code. Moving inline code to static files and using nonces/hashes would allow removal of `'unsafe-inline'` and materially strengthen XSS protection.
- FMIS validates uploads but does not include an antivirus engine. Scan uploads at the gateway or storage layer in production.
- Software cannot prevent an authorized staff member from misusing information they are permitted to see. Apply least privilege, staff training, audit review, and account deactivation procedures.
- Security must be re-tested after every feature, dependency, infrastructure, or permission change.
