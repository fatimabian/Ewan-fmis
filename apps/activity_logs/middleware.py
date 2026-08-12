import logging


logger = logging.getLogger(__name__)


class ActivityLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.user.is_authenticated
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and response.status_code < 400
            and not getattr(request, "_fmis_activity_recorded", False)
        ):
            from .services import log_activity

            try:
                log_activity(
                    request.user,
                    f"{request.method} {request.path}",
                    request.path,
                )
            except Exception:
                # The protected view has already completed at this point. Do not
                # replace a successful save with a misleading 500 response.
                logger.exception(
                    "Activity logging failed after a successful %s request to %s.",
                    request.method,
                    request.path,
                )
        return response
