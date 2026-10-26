from django.db.models import Count, Q

from apps.authentication.models import CustomUser


def account_summary():
    return CustomUser.objects.filter(deleted_at__isnull=True).aggregate(
        total=Count("pk"),
        active=Count("pk", filter=Q(is_active=True)),
        admins=Count("pk", filter=Q(role="ADMIN")),
        staff=Count("pk", filter=Q(role="STAFF")),
    )
