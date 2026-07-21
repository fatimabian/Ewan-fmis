from .models import ServiceCatalog


def active_services():
    return ServiceCatalog.objects.filter(is_active=True)
