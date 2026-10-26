# FMIS performance optimization report

## Scope and safety

This pass optimizes the existing Django application without changing roles, business rules,
database relationships, map purpose, or report/export behavior. It does not deploy anything.

Production response time, browser rendering, CPU/RAM spikes, MariaDB execution plans, and
Waitress/Nginx saturation cannot be measured from the local SQLite test environment. Those
items are explicitly left for staging/production measurement rather than guessed.

## Actual issues found and changes made

| Area | Root cause found | Change |
| --- | --- | --- |
| Large list pages | Most list views used a fixed 10/15 row size and Accounts had no pagination. | Shared database pagination now defaults to 25 and permits only 10, 25, 50, or 100. Search/filter parameters survive page and size changes. Invalid pages clamp safely. |
| Farmer list | `prefetch_related("parcels__crops")` hydrated two complete relation trees that the template never rendered. | Removed both prefetches and restricted farmer columns with `only()`. |
| Intervention list | Recipient farmers were prefetched even though the list uses an annotated beneficiary count. | Removed the unused prefetch. |
| Shared navigation | Every authenticated page separately queried notification preview rows and unread count. | A filtered window count supplies both from one notification query. |
| Map initial response | Private farmer/popup fields were sent for every pin even though most pins are never selected. | The authenticated marker endpoint now returns compact marker/filter fields only. Farmer name, area, address, and edit URL are fetched from an authenticated per-parcel endpoint only when a pin is selected. In-flight detail requests are deduplicated and results cached in the page. |
| Map rendering | Thousands of markers could block the browser in one synchronous loop. | Existing asynchronous loading now prepares pins in animation-frame batches with progress feedback. All required pins remain individually visible; no overview behavior was removed. |
| Dashboard | All aggregate queries ran on every dashboard request. | Admin and staff results use a short 30-second production cache. Model save/delete signals invalidate the appropriate cache immediately. Recent querysets are limited and materialized before caching. Tests/local development keep caching disabled. |
| Dashboard aggregates | Several related totals were issued as separate counts. | Farmer, parcel, account, activity, and report totals use filtered SQL aggregates where applicable. |
| Reports overview | Farmer statistics, account statistics, activity totals, and general totals caused 20 simple count queries in addition to report-detail queries. | Consolidated those 20 count operations into 6 aggregate operations; pending request and intervention totals reuse already-computed aggregates. |
| Static/module loading | Base JavaScript is already deferred; Leaflet is only loaded by the map; dashboard JavaScript is only loaded by the staff dashboard. | Preserved this correct page-specific behavior; no dependency or SPA rewrite added. |

## Measured comparison

Measurements below are deterministic query-path comparisons and automated local tests. They
are not presented as VPS latency numbers.

| Workload | Before | After |
| --- | ---: | ---: |
| Farmer collection query path | 4 queries: count, page, parcel prefetch, crop prefetch | 2 queries: count and 25-row page |
| Shared preference/notification context | 3 queries | 2 queries |
| Reports overview simple total/count operations | 20 queries | 6 aggregate queries |
| Dashboard repeat within cache window | Full dashboard service queries each request | Cached service result until 30 seconds or immediate model invalidation |
| Farmer list with 5,000 added records | No prior scale regression test | 25 rendered rows; no more than 13 total request queries including session/auth/navigation/filter choices |

The 5,000-record test completed in about 3.3 seconds on local Windows SQLite, including test
database setup and insertion. That elapsed value is not comparable to MariaDB production;
the useful result is that query count remains bounded as the dataset grows.

## Duplicate detection finding

The repository does not contain Random Forest or Levenshtein duplicate detection. The current
registration form performs an exact duplicate lookup for a non-empty valid ID number. That
lookup remains unchanged. There is no ML model load or all-farmer similarity loop to optimize
or benchmark in this codebase. If such logic exists only on the production server, reconcile
the deployed revision with this repository before changing it.

## Index review

No speculative index migration was added. The local database has no representative production
tables/data, and SQLite plans would not validate MariaDB behavior. Before adding indexes, run
`EXPLAIN`/`EXPLAIN ANALYZE` in staging for the real filtered list queries, especially barangay,
registration status, active flags, crop type, request status/priority, and date ordering. Add
only indexes proven useful by those plans and remeasure write cost.

## Production configuration review

- Database persistent connections and health checks are already configured; the default
  connection max age is 60 seconds.
- The example service uses Waitress with 16 threads, connection limit 250, and backlog 256.
  Do not raise these blindly. Measure concurrent request queues, MariaDB connections, memory,
  and p95 latency first.
- Nginx already serves the reverse proxy and blocks direct `/media/` access. Static collection
  remains part of deployment.
- `DASHBOARD_CACHE_SECONDS` defaults to 30 in production and can be tuned through the
  environment. Keep it short unless the measured workload supports a longer interval.

## Verification

- Full Django suite: 164 tests passed in 53.0 seconds.
- Added coverage for bounded page sizes, invalid/stale page numbers, Accounts pagination,
  unused Farmer prefetch removal, one-query notification preview/count, compact map data and
  on-demand details, dashboard caching/invalidation, and the 5,000-record Farmer list.
- `manage.py check`: no issues.
- `manage.py makemigrations --check --dry-run`: no model changes detected.

## Staging measurement and deployment sequence

1. Create and verify a database/media backup. Restore it to staging or a safe copy.
2. Record p50/p95 response time, query count/time, response bytes, browser load/render time,
   CPU, RAM, and MariaDB connections for Farmer list/search, Parcels, Map, both dashboards,
   module navigation, Reports, and registration.
3. Run MariaDB `EXPLAIN` for the slow queries before proposing indexes.
4. Deploy the code to staging and run `python manage.py check`, `python manage.py migrate
   --noinput`, and `python manage.py collectstatic --noinput`.
5. Restart the FMIS service and verify health plus ADMIN/STAFF permissions and workflows.
6. Repeat the identical workload and compare p50/p95, query duration, payload size, CPU/RAM,
   and errors. Use `scripts/Measure-FMISLoad.py` only against safe read-only URLs and with a
   concurrency level representative of actual use.
7. Roll back to the previous Git revision and restore the verified backup only if a schema/data
   rollback is required. Do not reset or overwrite the production database casually.
