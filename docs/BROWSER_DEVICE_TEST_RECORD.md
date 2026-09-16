# Browser, Mobile, and Responsive Test Record

Complete this sheet against the production candidate after HTTPS and MySQL are configured. Attach one desktop and two mobile screenshots per required module.

| Environment | Landing/Login | Admin dashboard | Staff dashboard | Farmers & forms | Reports & filters | Result | Tester/date |
|---|---|---|---|---|---|---|---|
| Google Chrome desktop, current supported version |  |  |  |  |  | Pending |  |
| Microsoft Edge desktop, current supported version |  |  |  |  |  | Pending |  |
| Mozilla Firefox desktop, current supported version |  |  |  |  |  | Pending |  |
| Android Chrome, portrait and landscape |  |  |  |  |  | Pending |  |
| iOS Safari, portrait and landscape |  |  |  |  |  | Pending |  |

For each cell verify: text is readable; no horizontal page overflow; navigation remains usable; fields, dropdowns, and buttons are reachable; validation messages are visible; dialogs can be closed; tables can be scrolled without losing actions; PDF/CSV generation succeeds.

## Required screenshot naming

- `landing-desktop.png`, `login-mobile.png`
- `admin-dashboard-desktop.png`, `admin-dashboard-mobile.png`
- `staff-dashboard-desktop.png`, `staff-dashboard-mobile.png`
- `farmer-form-mobile.png`, `report-filters-mobile.png`

Do not create “Customer Dashboard” screenshots. FMIS has no customer account role; farmers are indirect service beneficiaries whose records are managed by authorized staff.

## Local preflight completed September 16, 2026

The Codex in-app Chromium browser passed local preflight checks at 1440×900, 768×1024, and 390×844 for the landing/login page, staff dashboard, farmer registration, service requests, reports, administrator accounts, governance reports, settings, password recovery, and backup status. No page-level horizontal overflow was detected. The report statistics heading-to-card gap measured 8 pixels after correction.

This local preflight does not replace the production HTTPS and real-device/browser rows above; those remain pending until the deployment URL and devices are available.
