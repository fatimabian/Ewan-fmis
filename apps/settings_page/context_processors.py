def user_preference(request):
    preference = None
    notifications = []
    unread_count = 0
    session_timeout_seconds = 0
    if request.user.is_authenticated:
        from .models import SystemSetting, UserPreference
        from apps.notifications.models import Notification
        from django.db.models import Count, IntegerField, Subquery, Value
        from django.db.models.functions import Coalesce
        preference, _ = UserPreference.objects.get_or_create(
            user=request.user, defaults={"linked_email": request.user.email}
        )
        if preference.in_app_notifications:
            # A scalar indexed count plus the five recent rows avoids a window
            # function over the user's complete notification history while
            # preserving one notification query per authenticated page.
            unread_subquery = (
                Notification.objects.filter(
                    recipient=request.user,
                    is_read=False,
                )
                .values("recipient")
                .annotate(total=Count("pk"))
                .values("total")[:1]
            )
            user_notifications = Notification.objects.filter(
                recipient=request.user
            ).annotate(
                unread_total=Coalesce(
                    Subquery(unread_subquery, output_field=IntegerField()),
                    Value(0),
                )
            )
            notifications = list(user_notifications[:5])
            unread_count = notifications[0].unread_total if notifications else 0
        # Remembered sign-ins use their fixed seven-day window. Browser-only
        # sessions receive the administrator's inactivity limit in the page so
        # an open tab can log out without waiting for another navigation.
        session = getattr(request, "session", None)
        if session is not None and not session.get("fmis_remember_until"):
            session_timeout_seconds = max(
                60,
                int(SystemSetting.load().session_timeout) * 60,
            )
    return {
        "user_preference": preference,
        "notification_preview": notifications,
        "notification_unread_count": unread_count,
        "session_timeout_seconds": session_timeout_seconds,
    }
