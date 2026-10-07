def _actor_details(actor):
    if actor is None:
        return {
            "actor": "System / former account",
            "actor_username": "",
            "actor_role": "System",
        }
    return {
        "actor": actor.display_name,
        "actor_username": actor.username,
        "actor_role": actor.get_role_display(),
    }


def farmer_update_rows(entries):
    return [
        {
            "date": entry.created_at,
            **_actor_details(entry.actor),
            "audit_id": f"FUH-{entry.pk:06d}",
            "title": entry.get_update_type_display(),
            "transaction_code": entry.transaction_code,
            "status": "Completed",
            "status_label": "Update status",
            "reason": (
                entry.remarks
                if entry.update_type == "STATUS"
                else " · ".join(
                    value
                    for value in (entry.get_change_reason_display(), entry.remarks)
                    if value
                )
            ),
            "changes": entry.changes,
        }
        for entry in entries
    ]


def activity_rows(entries):
    return [
        {
            "date": entry.created_at,
            **_actor_details(entry.actor),
            "audit_id": f"AL-{entry.pk:06d}",
            "title": entry.title or entry.action,
            "transaction_code": "",
            "status": entry.status,
            "status_label": "Activity status",
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
            **_actor_details(entry.actor),
            "audit_id": f"SRH-{entry.pk:06d}",
            "title": entry.get_action_display(),
            "transaction_code": "",
            "status": status,
            "status_label": "Status change",
            "reason": "",
            "changes": entry.changes,
        })
    return rows
