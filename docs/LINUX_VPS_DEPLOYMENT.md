# FMIS Linux VPS deployment

This guide targets Ubuntu 24.04 LTS on a small Hostinger VPS. Commands assume an
administrator account with `sudo`; the application runs as the unprivileged
`fmis` service account.

## 1. Prepare the host

Install Python build tools, MySQL, Nginx, Git, rclone, and Certbot. Keep only SSH,
HTTP, and HTTPS open in UFW. Create `/srv/fmis`, `/etc/fmis`, `/var/log/fmis`, and
`/var/backups/fmis`, owned as narrowly as the service requires.

## 2. Install the release

Clone the reviewed release into `/srv/fmis/app`, create `/srv/fmis/venv`, install
`requirements.txt`, and copy `deployment.env.example` to
`/etc/fmis/fmis.env`. Never store the completed environment file in Git.

Create a least-privilege MySQL database user. Run migrations, `collectstatic`,
and `check --deploy` with the production environment loaded.

## 3. Start the application

Copy `deployment/linux/fmis.service.example` to
`/etc/systemd/system/fmis.service`, then enable and start it. Waitress listens
only on `127.0.0.1:8080`; it must never be exposed directly to the internet.

Copy `deployment/linux/nginx-fmis.conf.example` to the Nginx sites directory,
replace the example hostname, test the Nginx configuration, and enable it. The
configuration deliberately blocks direct `/media/` access.

## 4. Add the domain and HTTPS

Point the domain's A record to the VPS IPv4 address. After DNS resolves, obtain a
Let's Encrypt certificate with Certbot and verify HTTP redirects to HTTPS. Only
then enable the one-year HSTS setting in production.

## 5. Configure encrypted off-site backups

Configure an office-owned Google Drive remote with `rclone config`, move its
configuration to `/etc/fmis/rclone.conf`, and protect it with mode `0640` and the
`fmis` group. Set `BACKUP_RCLONE_REMOTE=gdrive:fmis-production` and
`RCLONE_CONFIG=/etc/fmis/rclone.conf`. Keep the existing
`FMIS_BACKUP_ENCRYPTION_KEY` offline as well as in the protected server
environment.

Copy the backup service and timer examples into `/etc/systemd/system`, run one
backup manually, verify that its encrypted `.fmisbak` file exists both locally
and in Google Drive, and restore it into a separate test database. Set
`FMIS_BACKUP_SCHEDULER_CONFIGURED=True` only after the timer and restoration test
pass.

## 6. Release gate

Run `python manage.py check_fmis_readiness`, test `/health/` externally, and test
login, email verification, MFA, QR access, uploads, deletion history, reports,
and backup restoration. Do not open the system to the office until all checks
pass over the final HTTPS hostname.
