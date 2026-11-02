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

## Scan & Auto-Fill (AI-assisted form digitization and location validation)

Scan & Auto-Fill is one shared control (`templates/form_scan/_scan_panel.html`) used by three pages. It shows only a **Scan & Auto-Fill** button with an (i) tip; the upload module opens in a dialog when the button is used:

- **Add Farm Parcel** and **Add Commodity**: staff photograph a handwritten form, review the values next to the photo, confirm them, and the form opens already filled in.
- **Farmer Registration**: the RSBSA page 1 photo fills the profile fields in place; fields the reader was unsure about are highlighted. The RSBSA record copies upload below it is unchanged and never fills the form.

Nothing is saved until staff press the form's own Save/Submit button. To use the panel on another form, include it and provide `scan_target` (`PARCEL`, `CROP` or `FARMER`).

**Flow:** photo upload (type and size checked by content) → OCR with per-field confidence → rule checks → review screen with the photo, a Leaflet map and a traffic light → staff confirm or edit → the target form opens pre-filled → on Save the audit trail and corrections are written.

**Traffic light:** GREEN all checks passed; YELLOW low confidence or a minor mismatch (can still be confirmed); RED outside Rosario, unreadable coordinates, barangay mismatch or overlap with an existing parcel (cannot be confirmed, and is re-checked again when the form is saved).

**Checks:** inside the Rosario boundary; swapped latitude/longitude, missing decimal point, dropped leading digit, wrong sign, and degrees-minutes-seconds (a correction is proposed with a "Use suggestion" button, never applied silently); pin inside the barangay written on the form; overlap (10 m) or near duplicate (50 m) with an existing parcel; farm area, including square metres and, when a drawn polygon exists, form area against polygon area.

**Audit trail:** every scan keeps who uploaded, who confirmed, what OCR suggested, which provider and model answered, what was changed and when. Each changed value is also stored in `FieldCorrection` (OCR value, final value, confidence, model) for later learning. Nothing is trained yet.

### Setup

1. `pip install -r requirements.txt` and `python manage.py migrate` (adds `ocr` and `form_scan` tables).
2. Copy `.env.example` to `.env` and set:
   - `OCR_PROVIDER`: `openrouter` (default), `gemini` (direct Google API) or `sample` (made-up readings, no key, nothing leaves the machine).
   - `OPENROUTER_API_KEY` or `GEMINI_API_KEY`, and `OCR_MODELS` (comma separated, tried in order).
   - Optional: `OCR_DAILY_LIMIT` (default 40), `OCR_TIMEOUT_SECONDS`, `OCR_CONFIDENCE_THRESHOLD` (default 0.75).
3. Choose the models by testing them on **dummy or consented** forms: `python manage.py ocr_compare form1.jpg form2.jpg`. Images are sent to the outside provider.
4. Import the barangay boundaries (`import_rosario_barangay_boundaries`) so the "pin inside barangay" check is exact. Without them the check compares with the published barangay reference points and says it is approximate.
5. Uploaded photos are stored in `private_media/` (override with `FMIS_PRIVATE_MEDIA_ROOT`), outside `MEDIA_ROOT`, with no public URL, and are served only to signed-in staff.

### GIS Map

**GIS Map** (staff sidebar) shows one layer at a time: Farmers, Farm parcels, Commodities or Service requests. Filters: barangay, commodity and status. It uses three colours (green good, gold needs attention, navy neutral), one icon per layer, and three levels of information: a heat map of where records are (with a short list of the busiest barangays), individual pins once a barangay is chosen, then a short record card with a link to the record.

### Limitations

- OCR uses a free-tier or paid outside service: there is a daily request cap (`OCR_DAILY_LIMIT`), models change, and the system needs internet access for it. When OCR is unavailable the form simply opens for manual entry.
- Handwriting accuracy varies by model and photo quality. Always compare with the photo; the low-confidence highlight is a hint, not a guarantee.
- The database is MySQL, so geometry runs in plain Python (no PostGIS). Overlap checks scan the pinned parcels and are meant for municipal scale.
- Parcels have no drawn polygon field yet, so the area-versus-polygon check only runs when a polygon is supplied to a scan.
- The farmer registration scan reads JPG or PNG photos (not PDFs) and only RSBSA page 1. Choose its reader with `RSBSA_SCAN_ENGINE` (`auto` uses OpenRouter/Gemini when configured, otherwise the older OpenAI reader; `ocr` or `openai` force one).

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
