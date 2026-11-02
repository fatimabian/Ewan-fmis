from django.conf import settings

DEFAULTS = {
    "PROVIDER": "openrouter",
    "MODELS": [],
    "OPENROUTER_API_KEY": "",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "GEMINI_API_KEY": "",
    "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
    "DAILY_LIMIT": 40,
    "TIMEOUT_SECONDS": 45,
    "MAX_IMAGE_BYTES": 8 * 1024 * 1024,
    "MAX_IMAGE_SIDE": 1600,
    "CONFIDENCE_THRESHOLD": 0.75,
    "FIELDS": [
        "farmer_name",
        "barangay",
        "parcel_name",
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
