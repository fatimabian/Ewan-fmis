from django.db import migrations


RECORD_LABELS = {
    "Farmers": "farmer record",
    "Farm Parcels": "farm parcel",
    "Crops": "crop record",
    "Service Requests": "service request",
    "User Accounts": "user account",
}


def make_notifications_plain_language(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")

    for notification in Notification.objects.select_related("source_activity__actor").all():
        activity = notification.source_activity
        if activity is None:
            continue

        actor = activity.actor
        if actor is None:
            actor_name = "The system"
        else:
            actor_name = " ".join(
                part for part in (actor.first_name, actor.last_name) if part
            ).strip() or actor.username or "A staff member"

        activity_title = (activity.title or "").casefold()
        if activity.module == "Security" or activity.status.casefold() != "success":
            if "access denied" in activity_title:
                title = "Restricted page blocked"
                message = f"{actor_name} tried to open a page that is not available for their account. No changes were made."
            elif "sign-in blocked" in activity_title:
                title = "Sign-in temporarily blocked"
                message = "Several incorrect sign-in attempts were blocked. No account access was granted."
            elif "failed sign-in" in activity_title:
                title = "Unsuccessful sign-in"
                message = "Someone entered incorrect sign-in details. No account access was granted."
            else:
                title = "Action needs attention"
                message = activity.description or "An action could not be completed. Open the activity page for more information."
        else:
            record_label = RECORD_LABELS.get(activity.module, "record")
            if "created" in activity_title:
                verb = "created"
            elif "archived" in activity_title:
                verb = "archived"
            elif "restored" in activity_title:
                verb = "restored"
            else:
                verb = "updated"
            target = (activity.target_label or "").strip()
            message = (
                f"{actor_name} {verb} the {record_label} for {target}."
                if target and not target.startswith("/")
                else f"{actor_name} {verb} a {record_label}."
            )
            title = activity.title or f"{record_label.title()} updated"

        notification.title = title
        notification.message = message[:255]
        notification.save(update_fields=("title", "message"))


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]

    operations = [migrations.RunPython(make_notifications_plain_language, migrations.RunPython.noop)]
