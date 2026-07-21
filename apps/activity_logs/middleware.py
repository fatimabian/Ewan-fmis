class ActivityLogMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and request.method in {"POST", "PUT", "PATCH", "DELETE"} and response.status_code < 400:
            from .services import log_activity
            log_activity(request.user, f"{request.method} {request.path}", request.path)
        return response
