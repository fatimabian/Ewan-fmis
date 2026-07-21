from apps.authentication.models import CustomUser
def account_summary():
    return {"total": CustomUser.objects.count(), "active": CustomUser.objects.filter(is_active=True).count(), "admins": CustomUser.objects.filter(role="ADMIN").count(), "staff": CustomUser.objects.filter(role="STAFF").count()}
