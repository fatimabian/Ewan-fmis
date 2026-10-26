# FMIS farm parcel coordinate audit

## Findings

- The map endpoint reads each active parcel's own `FarmParcel.coordinates` value.
- Leaflet receives coordinates in the correct `[latitude, longitude]` order.
- Barangay filtering uses exact equality (`item.barangay === selectedBarangay`). It does not move markers.
- The old permanent barangay label was calculated from the visible marker cluster. That could make suspicious saved coordinates appear to be the true barangay location; the label has been removed.
- The demo-data generator assigned synthetic points near barangay reference centres. Those are not verified parcel locations. Newly generated demo parcels are now left unmapped.
- Existing production coordinates are not rewritten by this change. Duplicates, reference-centre matches, invalid values, zero values, and points outside the municipal reference boundary are reported for manual review.

Tulos is in Rosario's southeast district. A published locality reference is approximately `13.7231, 121.2971`; this reference must not be copied into farm parcel records unless it is the parcel's independently verified position.

## Read-only production audit

Run from `/srv/fmis/app` as the application user:

```bash
/srv/fmis/venv/bin/python manage.py audit_parcel_coordinates --summary-only
/srv/fmis/venv/bin/python manage.py audit_parcel_coordinates --barangay Tulos --output /tmp/fmis-tulos-coordinate-audit.json
```

The command reads parcel IDs, barangays, and coordinates only. It does not update or delete data and does not include farmer names or contact information.

## Map behavior after the change

- Nearby markers are clustered without altering their coordinates.
- Markers sharing an identical coordinate can be spiderfied and opened individually.
- Clicking a visible red pin immediately pans the map to it, then loads its protected popup details.
- Selecting a parcel through search expands its cluster before opening the parcel.
- Switching barangays uses the saved marker coordinates and updates mapped/unmapped counts for that barangay.
- Marker responses use `Cache-Control: no-store` to prevent stale coordinates after a correction.
- Right-click movement continues to update only the selected parcel and records the before/after coordinate in activity history.

## Manual review rule

A flagged coordinate is not automatically wrong. Shared coordinates can be legitimate. Staff should compare flagged records with field GPS/GPX evidence and move or remove only the affected parcel through the existing authorized map workflow.

## Geographic references

- Rosario LGU barangay districts: https://www.lgurosariobatangas.com/p/barangay-affairs.html
- Tulos locality reference: https://www.philatlas.com/luzon/r04a/batangas/rosario/tulos.html
