from apps.authentication.models import CustomUser


def account_summary():
    accounts = CustomUser.objects.filter(deleted_at__isnull=True)
    return {
        "total": accounts.count(),
        "active": accounts.filter(is_active=True).count(),
        "admins": accounts.filter(role="ADMIN").count(),
        "staff": accounts.filter(role="STAFF").count(),
    }
