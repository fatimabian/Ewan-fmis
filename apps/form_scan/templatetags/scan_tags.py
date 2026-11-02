from django import template

from apps.ocr import services as ocr
from apps.ocr.conf import ocr_setting
from apps.ocr.uploads import ALLOWED_EXTENSIONS, max_megabytes

register = template.Library()


@register.simple_tag
def scan_limits():
    """The rules shown in the Scan & Auto-Fill dialog, read from the same settings that enforce them."""
    return {
        "max_files": ocr_setting("MAX_FILES"),
        "max_mb": max_megabytes(),
        "extensions": [extension.lstrip(".").upper() for extension in ALLOWED_EXTENSIONS],
        "accept": ",".join(ALLOWED_EXTENSIONS),
        "daily_limit": ocr_setting("DAILY_LIMIT"),
        "left": ocr.requests_left_today(),
        "sample": ocr_setting("PROVIDER") == "sample",
    }
