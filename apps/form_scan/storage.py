from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """File storage that refuses to build a URL, so a scan can never be linked publicly."""

    def url(self, name):
        raise ValueError("Scanned forms are private and have no public URL.")


def private_storage():
    """Storage outside MEDIA_ROOT; images are served only by the staff-only image view."""
    return PrivateStorage(location=settings.PRIVATE_MEDIA_ROOT)
