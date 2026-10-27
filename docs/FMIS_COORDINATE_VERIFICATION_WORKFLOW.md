# FMIS coordinate audit and verification workflow

## Safety boundary

The audit command is read-only. It never changes parcel coordinates, barangays,
farmers, or map records. Database credentials remain in the production server's
environment (`DB_ENGINE`, `MYSQL_*`) and must not be supplied as command-line
arguments, pasted into chat, or committed to Git.

Run on the authorized application server, preferably against a read replica or
during a low-traffic maintenance window:

```bash
python manage.py audit_parcel_coordinates --summary-only
python manage.py audit_parcel_coordinates --format json --output /secure/audits/parcel-coordinates.json
python manage.py audit_parcel_coordinates --format csv --output /secure/audits/parcel-coordinates.csv
```

The command refuses to overwrite an existing report and requests owner-only
file permissions where the operating system supports them. Reports contain
only parcel ID, barangay, PSGC code, current coordinates, detected issue, and a
recommended verification action. Farmer names, RSBSA numbers, contact details,
and addresses are excluded.

Detected issues:

- missing or malformed coordinates;
- zero coordinates and coordinates outside the Rosario municipal boundary;
- exact duplicate coordinates shared by multiple parcels;
- coordinates matching known reference centres within three metres;
- synthetic demo locations marked by the existing FMIS demo prefix;
- coordinates outside the assigned barangay, but only after all 48 approved
  PSGC-matched barangay polygons have been imported.

## Authoritative geography

Rosario, Batangas has municipality PSGC `0401021000`. Its 48 barangay names and
codes are defined in `apps/common/constants.py` from the official PSA list.
PSA PSGC is authoritative for identifiers and names, not parcel coordinates.

Candidate polygon data must be obtained through NAMRIA / Geoportal Philippines
or another formally approved government source. Do not trace screenshot labels,
generate Voronoi areas around barangay centres, or treat reference points as
boundaries. Keep the source URL, version, and SHA-256 checksum with every import.

The prepared importer accepts a local, authorized GeoJSON file and refuses
partial datasets, mismatched PSGC/name pairs, duplicate codes, unsupported
geometry, and checksum mismatches:

```bash
python manage.py import_rosario_barangay_boundaries boundaries.geojson \
  --source-agency "NAMRIA / Geoportal Philippines" \
  --source-url "https://geoportal.gov.ph/..." \
  --dataset-version "approved release identifier" \
  --expected-sha256 "approved file checksum" \
  --dry-run
```

Remove `--dry-run` only after OAS has confirmed the license, provenance, CRS
(WGS84 / EPSG:4326), completeness, and visual alignment. The importer does not
download data and therefore does not need an API token or network credentials.

Official references:

- PSA Rosario barangay list: https://psa.gov.ph/classification/psgc/barangays/0401021000
- PSA PSGC API documentation: https://psa.gov.ph/classifications-api/psgc
- Geoportal Philippines: https://www.geoportal.gov.ph/

## Review and approval lifecycle

1. A staff map edit creates `ParcelCoordinateReview`; it does not modify the
   live `FarmParcel.coordinates` value.
2. The proposal stores the original value, proposed value/removal, issue codes,
   evidence source, optional evidence reference, notes, submitter, and time.
3. Authorized staff review it on `/parcels/map/verification/` or in the map side
   panel/popup. The screen intentionally identifies the parcel and barangay
   without exposing unrelated farmer personal information.
4. Approval locks the proposal and parcel row in one database transaction. A
   stale proposal is rejected when its original snapshot no longer equals the
   current parcel coordinate.
5. Approval updates only that parcel, creates immutable
   `ParcelCoordinateHistory`, clears map-count caches, and returns the parcel ID.
   The Leaflet client reloads the current barangay layer, red pin, popup,
   side-panel row, counts, and filters without reloading the page.
6. Rejection leaves the parcel unchanged.
7. Reversal restores the recorded before-value only when the approved value is
   still current. This prevents an old reversal from overwriting a newer fix.

The `FarmParcel(is_active, barangay)`, review status, parcel-review, and
parcel-history indexes keep common map and verification queries bounded as the
dataset grows beyond 5,000 parcels.

## Production sequence (requires separate approval)

1. Back up and verify the production database.
2. Run the read-only audit and have OAS review the de-identified report.
3. Apply schema migrations; do not run coordinate update scripts.
4. Validate any authoritative polygon file with `--dry-run` before import.
5. Smoke-test proposal, approval, rejection, and reversal with designated test
   parcels.
6. Deploy only after explicit approval. No existing production coordinate is
   changed merely by applying these migrations.
