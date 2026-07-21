def user_preference(request):
    preference = None
    if request.user.is_authenticated:
        from .models import UserPreference
        preference, _ = UserPreference.objects.get_or_create(user=request.user, defaults={"linked_email": request.user.email})
    return {"user_preference": preference}
