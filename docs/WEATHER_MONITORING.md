# FMIS Weather-Triggered Service Request Workflow

## Safety and scope

This feature records completed-day, model-estimated precipitation and creates a
preliminary area review. It does not diagnose waterlogging, disease, or crop
damage. No Service Request is created until an authorized FMIS user approves the
review. Existing manual requests are unchanged.

The scheduler is disabled by default. Production activation requires:

1. OAS approval of each rainfall rule and coverage area.
2. Review of Open-Meteo's current licence and attribution requirements.
3. `FMIS_WEATHER_LICENSE_REVIEWED=True` in the server environment.
4. A securely installed systemd timer and
   `FMIS_WEATHER_SCHEDULER_CONFIGURED=True`.

Open-Meteo's free endpoint is limited to non-commercial use. Its weather data is
CC BY 4.0 and requires attribution. If the deployment needs a commercial plan,
use the customer endpoint and API key. Confirm the current terms at
https://open-meteo.com/en/terms and https://open-meteo.com/en/pricing before
activation.

## Data flow

1. `python manage.py monitor_weather` runs outside web requests.
2. One bounded API call per active coverage area retrieves completed local days
   in `Asia/Manila`. Timeouts and three total attempts are enforced.
3. Observations are unique by coverage area and date. Missing/incomplete data
   creates no alert and never overwrites previous records.
4. Only active, formally approved rules are evaluated. The configured daily,
   consecutive-day, accumulated-rainfall, and cooldown values must all pass.
5. FMIS matches active parcels by actual saved WGS84 coordinates and configured
   radius. Missing, invalid, out-of-town, and demo placeholder coordinates are
   excluded and counted for verification.
6. One idempotent `WeatherRiskEvent` is created per area/rule/period and links
   the matching parcels and recorded crops.
7. Staff review the event. Approval creates one pending Crop Monitoring Support
   request per affected barangay, not one per farmer. Dismissal requires a
   reason. Both decisions are logged.

## Performance

Normal pages never call the weather provider or scan parcel coordinates.
Weather work runs only in the management command. Database uniqueness guards
repeated runs, API calls are skipped when the required dates already exist, and
parcel writes use a bounded iterator and batched inserts. Dashboard queries are
small indexed aggregates and use the existing dashboard cache.

## Production installation

Copy the example service and timer into `/etc/systemd/system/`, remove the
`.example` suffix, then run:

```text
sudo systemctl daemon-reload
sudo systemctl enable --now fmis-weather-monitor.timer
sudo systemctl list-timers fmis-weather-monitor.timer
```

Do not enable the timer until the environment gates and at least one OAS-approved
rule are in place. Run a manual dry operational check with:

```text
sudo systemctl start fmis-weather-monitor.service
sudo journalctl -u fmis-weather-monitor.service --since today
```

## Manual verification

- Confirm manual service-request creation/editing still works.
- Confirm staff can view events and administrators can configure rules.
- Confirm a staff account cannot open the administrator settings page.
- Confirm missing or invalid weather data creates no event.
- Confirm invalid/unverified coordinates are excluded.
- Confirm rerunning the command does not duplicate observations or events.
- Confirm approval creates only the expected barangay request(s).
- Confirm dismissal requires and stores a reason.
- Confirm analytics labels exposure as preliminary and not crop damage.
