# Service request escalation and ITSM metrics

## Proposed targets

These defaults are proposals pending formal OAS approval. The Administrator records approval in **Settings → System → Service Request Targets**.

| Priority | First response target | Completion target |
|---|---:|---:|
| High | 24 elapsed hours | 72 elapsed hours |
| Medium | 3 elapsed days | 4 elapsed days |
| Low | 5 elapsed days | 7 elapsed days |

`Pending`, `In Progress`, `Completed`, and `Cancelled` remain workflow statuses. `Overdue` is calculated independently, so a request can be both `Pending` and `Overdue`, or `In Progress` and `Overdue`.

The first response is recorded only when status first becomes `In Progress` or `Completed`. Opening a page, sending an automated notification, or editing text while still Pending does not count. Completion is recorded when status becomes Completed. Reopening clears the current completion timestamp; the prior transition remains in request history.

Historical requests are not assigned invented response, completion, or feedback timestamps. Missing historical measurements display as `N/A`.

## Scheduled escalation

Install the example `fmis-escalation.service` and `fmis-escalation.timer` units from `deployment/linux`, then enable the timer. The command is idempotent:

```text
/srv/fmis/venv/bin/python manage.py process_service_escalations
```

It records each request/deadline escalation once, writes request history, and creates in-app notifications for the assigned staff member and active administrators. It never reassigns a request.

## Metric definitions

- Average response: elapsed creation-to-first-response time, excluding missing timestamps.
- Average turnaround: elapsed creation-to-completion time for completed requests with valid timestamps.
- Resolution rate: requests created in the selected cohort and completed by the report cutoff, divided by all requests created in the cohort.
- Open backlog: requests not Completed or Cancelled.
- Overdue: open requests beyond the applicable response or completion target.
- Backlog aging: elapsed age grouped into 0–1, 2–3, 4–7, and more than 7 days.
- Satisfaction: optional farmer-reported rating recorded by authorized staff after completion. No value is inferred.

## Deployment and rollback

Before production deployment, back up the database, apply migration `service_requests.0005`, collect static files, restart FMIS, and enable the timer only after confirming the OAS-approved schedule. Rollback requires disabling the timer first. Application rollback may reverse migration `0005`; doing so removes the new policy, timestamps, feedback, and escalation tables, so export those values first if they must be retained.
