from django.conf import settings

DEFAULTS = {
    "PROVIDER": "openrouter",
    "MODELS": [],
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "GEMINI_API_KEY": "",
    "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
    # Photos read per day, counted once per photo (a three page form uses three).
    "DAILY_LIMIT": 30,
    "TIMEOUT_SECONDS": 45,
    "MAX_IMAGE_BYTES": 5 * 1024 * 1024,
    "MAX_FILES": 3,
    "MAX_IMAGE_SIDE": 1600,
    "CONFIDENCE_THRESHOLD": 0.75,
    "FIELDS": [
        "farmer_name",
        "barangay",
        "latitude",
        "longitude",
        "area_hectares",
        "commodity",
        "ownership_type",
    ],
}


def ocr_setting(name):
    """Read one OCR setting, falling back to the module default."""
    return {**DEFAULTS, **getattr(settings, "OCR", {})}[name]
