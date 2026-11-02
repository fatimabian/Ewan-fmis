from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_storage():
    """Storage outside MEDIA_ROOT with no public URL; images are served only by a staff view."""
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)
