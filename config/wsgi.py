import os

from django.conf import settings
from django.core.wsgi import get_wsgi_application

from config.startup import prewarm_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()

if not settings.DEBUG and os.getenv("FMIS_PREWARM_ON_START", "True").lower() == "true":
    warmup_host = next(
        (
            host
            for host in settings.ALLOWED_HOSTS
            if host != "*" and not host.startswith(".")
        ),
        "localhost",
    )
    prewarm_wsgi_application(application, host=warmup_host)
