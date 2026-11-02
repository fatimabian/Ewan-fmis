"""The confirmation staff give before a form photo is sent to an outside reading service."""
from apps.ocr.conf import ocr_setting

CONSENT_FIELD = "consent"


def photos_leave_the_system(farmer_registration=False):
    """True when scanning sends the photo outside FMIS (anything but the made-up sample mode)."""
    outside = ocr_setting("PROVIDER") != "sample"
    if farmer_registration:
        # The farmer page may use the older OpenAI reader, which also sends the photo outside.
        from django.conf import settings

        from apps.farmers.rsbsa_scan import ocr_engine_selected

        return outside if ocr_engine_selected() else bool(getattr(settings, "OPENAI_API_KEY", "").strip())
    return outside


def consent_given(post, farmer_registration=False):
    """Whether the request carries the confirmation, or none is needed."""
    return (not photos_leave_the_system(farmer_registration)) or post.get(CONSENT_FIELD) in {"1", "on", "true"}


CONSENT_MESSAGE = (
    "Confirm that you are allowed to scan this form and that the farmer has been told it may be read by an "
    "outside reading service."
)
