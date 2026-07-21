from functools import wraps
from django.core.exceptions import PermissionDenied


def admin_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
