def user_preference(request):
    preference = None
    notifications = []
    unread_count = 0
    session_timeout_seconds = 0
    if request.user.is_authenticated:
        from .models import SystemSetting, UserPreference
        from apps.notifications.models import Notification
        from django.db.models import Count, Q, Window

        preference, _ = UserPreference.objects.get_or_create(
            user=request.user, defaults={"linked_email": request.user.email}
        )
        if preference.in_app_notifications:
            # One windowed query supplies both the five preview rows and the
            # unread total. Previously every authenticated page paid for a
            # separate COUNT query before loading the same notification table.
            user_notifications = Notification.objects.filter(
                recipient=request.user
            ).annotate(
                unread_total=Window(
                    expression=Count("pk", filter=Q(is_read=False))
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
