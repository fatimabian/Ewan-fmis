# FMIS Data Governance and Incident Policy

This document is an operational template for approval by the Municipality of Rosario's authorized records, privacy, and information-security officers before production turnover. It does not replace an approved government records-disposition schedule or legal advice.

## Access and confidentiality

- Administrators govern accounts, audit activity, security, and recovery. They do not perform routine farmer-record encoding.
- Staff access farmer, parcel, crop, document, report, and service-request functions only for assigned official duties.
- Each user receives an individual account. Shared accounts and shared passwords are prohibited.
- Staff must sign a confidentiality acknowledgement before receiving access and must immediately report lost credentials or suspected disclosure.
- Access is removed when duties change or employment ends. Accounts are deactivated rather than deleted so their audit attribution remains intact.

## Data minimization

- The operational map records agricultural parcel coordinates, not farmer residence coordinates.
- Identity numbers are masked in ordinary detail screens.
- Supporting documents are opened through an authenticated staff endpoint and must not be exposed as a public web-server directory.
- PhilSys identifiers, identity-document copies, and any legacy residence coordinates must be retained or collected only when the Office documents the official purpose, authority, access group, and retention period.
- Free-text remarks must contain only information necessary for agricultural services.

## Retention decision register

The authorized records officer must complete this table before go-live. Until a period is approved, FMIS archives records and does not automatically destroy them.

| Record class | Approved retention period | Trigger | Authorized disposition | Approver/date |
| --- | --- | --- | --- | --- |
| Farmer registration and updates | To be approved | Superseded, inactive, or other official trigger | Archive / approved disposal | Pending |
| Farm parcels and crop records | To be approved | Parcel/crop becomes inactive | Archive / approved disposal | Pending |
| Service requests and history | To be approved | Request closure or cancellation | Archive / approved disposal | Pending |
| Identity/supporting documents | To be approved | Purpose completed or record closed | Restricted archive / approved disposal | Pending |
| User accounts and audit activity | To be approved | Account deactivation | Retain attribution / approved disposal | Pending |
| Encrypted backups | 7 daily, 4 weekly, 12 monthly minimum | Successful replacement backup | Automated encrypted rotation | Confirm before go-live |

## Privacy requests

Requests for access, correction, objection, or information about processing must be logged, verified, assigned to an authorized officer, and resolved within the period required by the Office's approved procedure. Staff must not alter official records solely from an unverified telephone or email request.

## Incident response

1. Preserve evidence and record the discovery time, reporter, affected system, and visible symptoms.
2. Contain exposure by disabling affected accounts, restricting network access, and preserving audit and server logs. Do not erase or overwrite evidence.
3. Notify the designated technical administrator and Data Protection Officer through the approved private channel.
4. Determine affected records, users, dates, exports, uploaded files, and backups.
5. Rotate exposed passwords, database credentials, storage SAS tokens, and encryption material as applicable.
6. Restore only from a verified recovery point into an isolated environment before returning the service to production.
7. Complete any required assessment, notification, corrective action, and post-incident review under the Municipality's approved process.

## Acceptance signatures

- Records/retention owner: ____________________ Date: __________
- Data Protection Officer: ____________________ Date: __________
- Information-security/technical owner: ____________________ Date: __________
- Office process owner: ____________________ Date: __________
