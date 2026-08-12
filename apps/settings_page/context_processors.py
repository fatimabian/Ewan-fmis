def user_preference(request):
    preference = None
    notifications = []
    unread_count = 0
    if request.user.is_authenticated:
        from .models import UserPreference
        from apps.notifications.models import Notification

        preference, _ = UserPreference.objects.get_or_create(
            user=request.user, defaults={"linked_email": request.user.email}
        )
        if preference.in_app_notifications:
            user_notifications = Notification.objects.filter(recipient=request.user)
            unread_count = user_notifications.filter(is_read=False).count()
            notifications = list(user_notifications[:5])
    return {
        "user_preference": preference,
        "notification_preview": notifications,
        "notification_unread_count": unread_count,
    }
