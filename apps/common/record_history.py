def farmer_update_rows(entries):
    return [
        {
            "date": entry.created_at,
            "actor": entry.actor.display_name if entry.actor else "System / former account",
            "title": entry.get_update_type_display(),
            "status": entry.transaction_code,
            "reason": " · ".join(
                value
                for value in (entry.get_change_reason_display(), entry.remarks)
                if value
            ),
            "changes": entry.changes,
        }
        for entry in entries
    ]


def activity_rows(entries):
    return [
        {
            "date": entry.created_at,
            "actor": entry.actor.display_name if entry.actor else "System / former account",
            "title": entry.title or entry.action,
            "status": entry.status,
            "reason": entry.reason or entry.description,
            "changes": entry.details,
        }
        for entry in entries
    ]


def service_request_rows(entries):
    status_labels = {
        "PENDING": "Pending", "IN_PROGRESS": "In Progress",
        "COMPLETED": "Completed", "CANCELLED": "Cancelled",
    }
    rows = []
    for entry in entries:
        status = ""
        if entry.from_status or entry.to_status:
            before = status_labels.get(entry.from_status, entry.from_status)
            after = status_labels.get(entry.to_status, entry.to_status)
            status = f"{before} → {after}" if before else after
        rows.append({
            "date": entry.created_at,
            "actor": entry.actor.display_name if entry.actor else "System / former account",
            "title": entry.get_action_display(),
            "status": status,
            "reason": "",
            "changes": entry.changes,
        })
    return rows
