from .models import ActivityLog


def _friendly_activity(method, path):
    labels = [
        ("/catalog/", "Service Catalog", "Service Catalogs", "added or updated an agricultural service in the catalog."),
        ("/farmers/", "Farmer Record", "Farmers", "added or updated a farmer record."),
        ("/parcels/", "Farm Parcel", "Farm Parcels", "added or updated a farm parcel record."),
        ("/crops/", "Crop Record", "Crops", "added or updated a crop record."),
        ("/requests/", "Service Request", "Service Requests", "created or updated a farmer service request."),
        ("/accounts/", "User Account", "User Accounts", "created or updated a user account."),
        ("/settings/", "Account Settings", "Settings", "updated account preferences and notification settings."),
    ]
    for fragment, subject, module, phrase in labels:
        if fragment in path:
            verb = "Created" if method == "POST" else "Updated"
            return f"{subject} {verb}", module, phrase
    return "System Record Updated", "FMIS", "updated a record in the Farmer Management Information System."


def log_activity(user, action, path):
    title, module, phrase = _friendly_activity(action.split()[0], path)
    actor_name = user.display_name if user.is_authenticated else "A user"
    return ActivityLog.objects.create(actor=user if user.is_authenticated else None, action=action, path=path, title=title, module=module, description=f"{actor_name} {phrase}")
