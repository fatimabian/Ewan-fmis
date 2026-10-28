# FMIS table toolbar audit and restoration plan

## Restoration baseline

- Baseline commit: `327303a` (`Refine report tables and map controls`)
- Backup branch: `backup/pre-toolbar-standard-20261029`
- Database changes: none planned
- Restore all toolbar work: `git revert` the toolbar implementation commit(s), or create a branch from `backup/pre-toolbar-standard-20261029`.
- Restore one module: restore that module's view and template from the baseline commit, then rebuild `static/css/fmis-core.min.css` if shared assets were restored.

The baseline preserves the original server-side pagination, search query names,
module actions, permissions, and table management workflows. The toolbar work
will rearrange those controls but will not remove their underlying behavior.

## Module audit and implementation plan

| Module | Users | Existing behavior and actions | Supported filters selected | Date meaning | Plan |
|---|---|---|---|---|---|
| Farmers | Admin and staff | Search; barangay, registration and active status; Add Farmer; paginated | Existing filters plus inclusive registration date | `Farmer.created_at` (record registration) | New compact toolbar/popover |
| Farm parcels | Admin and staff | Search; barangay, ownership, area and status; Map View; Add Parcel; paginated | Existing filters plus inclusive parcel registration date | `FarmParcel.created_at` | New compact toolbar/popover |
| Commodities | Admin and staff | Search; commodity and active status; Add Commodity; paginated | Existing filters, related farmer barangay, and inclusive planting date | `CropRecord.planting_date` | New compact toolbar/popover |
| Service requests | Admin and staff | Search; status and priority; New Request; paginated. Backend already supports more filters. | Request type, status, priority, assigned staff, overdue state and inclusive submission date | `ServiceRequest.created_at` | Expose supported operational filters in popover |
| Interventions | Admin and staff | Search; type and status; New Intervention; paginated | Type, status, related barangay and inclusive intervention date | `Intervention.intervention_date` | New toolbar/popover and requested custom dates |
| User accounts | Administrator only | Metrics, account table and New Account; paginated | Search, role and account status | No date filter: creation date is not needed for routine account administration | Add an admin-only toolbar/popover |
| Activity logs | Administrator only | Search; module and actor; paginated, expandable audit rows | Existing fields plus inclusive event date | `ActivityLog.created_at` | New admin-only toolbar/popover |
| Reports | Admin/staff according to existing report definitions | Purpose-built report category/filter/download interface | Already module-aware and supports custom dates | Defined per report exporter | Keep specialized interface; do not force table toolbar |
| Notifications, record histories, service-level policy | Contextual/read-only supporting interfaces | Specialized tables or feeds | No useful independent management filter | Not applicable | No toolbar; forcing one would add noise |

## Original layout record

Before this change, Farmers, Parcels, Commodities, Requests, and Interventions
showed search and every select filter inline above the table. Select changes
submitted immediately. Module-specific actions were at the right. Accounts had
only a table heading and New Account action. Activity Logs showed search, module,
and actor inline. All list pages used Django server-side pagination through
`FMISLoginRequiredMixin`, which preserved every query parameter except `page`.

## Files expected to change

- Shared: `apps/common/filters.py`, `static/css/table-toolbar.css`,
  `static/js/table-toolbar.js`, `scripts/build_frontend_assets.py`,
  `templates/base/base.html`, generated `static/css/fmis-core.min.css`, and
  generated `static/js/fmis-core.min.js`.
- Module views/templates: Farmers, Farm Parcels, Crops, Service Requests,
  Interventions, Accounts, and Activity Logs.
- Focused regression tests in the existing application test suites.

## Safety constraints

- No migrations or new database fields.
- Existing ORM permission mixins remain unchanged.
- All filtering remains server-side and paginated.
- Invalid or reversed date ranges return an inline error and do not apply a
  partial ambiguous range.
- Popover JavaScript only controls presentation; access and filtering remain
  enforced by Django views.
- No production deployment is part of this work.

## Local implementation record

| Module | Files | Implemented filters | Status |
|---|---|---|---|
| Farmers | `apps/farmers/views.py`, `templates/farmers/list.html` | Barangay, registration status, active status, registered from/to | Fits |
| Farm parcels | `apps/farm_parcels/views.py`, `templates/farm_parcels/list.html` | Barangay, ownership, area, record status, registered from/to | Fits |
| Commodities | `apps/crops/views.py`, `templates/crops/list.html` | Commodity, record status, farmer barangay, planted from/to | Fits |
| Service requests | `apps/service_requests/views.py`, `templates/service_requests/list.html` | Request type, status, priority, assigned staff, overdue state, submitted from/to | Fits |
| Interventions | `apps/interventions/views.py`, `templates/interventions/list.html` | Type, workflow/archive status, beneficiary barangay, intervention from/to | Fits |
| User accounts | `apps/accounts/views.py`, `templates/accounts/list.html` | Search, role, account status | Fits; date filter intentionally omitted |
| Activity logs | `apps/activity_logs/views.py`, `templates/activity_logs/list.html` | Module, authorized user, activity from/to | Fits |
| Reports | Existing report-specific filters retained | No toolbar conversion | Specialized design retained |
| Supporting/read-only tables | No changes | None | Toolbar not applicable |

Shared implementation files are `apps/common/filters.py`,
`static/css/table-toolbar.css`, `static/js/table-toolbar.js`, the frontend build
script, base asset references, generated bundles, and focused regression tests.

### Restoration by module

For one module, restore its view and list template from `327303a`. Shared
toolbar assets can remain safely because they activate only on elements marked
with `data-table-toolbar`. To remove the design globally, revert the toolbar
commit, which restores the original inline controls and generated bundles.

Restoration risks are limited to losing filter parameters introduced by this
change from bookmarked URLs; no stored records or schema are affected. Reverting
only a template without its corresponding view is discouraged because it can
leave supported filters inaccessible, although it does not alter data.

### Validation record

- Django system check: passed.
- Migration drift check (`makemigrations --check --dry-run`): no changes detected.
- JavaScript syntax check for the toolbar controller: passed.
- Four focused toolbar/date/permission regression tests: passed.
- Five initial management-list regressions: passed.
- Fifteen broader list, pagination, crop, request, and intervention regressions: passed.
- Thirty-two crop, service-request, intervention, pagination, and bounded-query tests: passed.
- Restoration test: a detached worktree was created from `327303a`, Django
  system check passed there, and the temporary worktree was removed successfully.
- Desktop/tablet/mobile behavior is implemented through explicit breakpoints;
  final visual acceptance should be performed in the target browsers before any deployment.
