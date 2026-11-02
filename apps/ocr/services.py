import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .conf import ocr_setting
from .exceptions import OcrProviderError, OcrUnavailable
from .imaging import prepare_image
from .models import OcrDailyUsage
from .parsing import build_prompt, parse_reply
from .providers import get_provider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FieldReading:
    value: str
    confidence: float


@dataclass(frozen=True)
class OcrResult:
    fields: dict
    provider: str
    model: str
    attempts: list = field(default_factory=list)


def reserve_request():
    """Count one provider request against today's cap; return False when the cap is reached."""
    limit = ocr_setting("DAILY_LIMIT")
    with transaction.atomic():
        OcrDailyUsage.objects.get_or_create(date=timezone.localdate())
        return bool(
            OcrDailyUsage.objects.filter(date=timezone.localdate(), count__lt=limit).update(
                count=F("count") + 1
            )
        )


def requests_left_today():
    """How many provider requests remain today."""
    used = (
        OcrDailyUsage.objects.filter(date=timezone.localdate()).values_list("count", flat=True).first()
        or 0
    )
    return max(0, ocr_setting("DAILY_LIMIT") - used)


def _field_names(fields):
    return list(fields or ocr_setting("FIELDS"))


def _read_with_model(provider, model, image, mime, names, instructions=""):
    """Ask one model and return parsed readings, counting the request against the cap."""
    if provider.name != "sample" and not reserve_request():
        raise OcrUnavailable("The daily OCR request limit has been reached.")
    reply = provider.read(model, image, mime, build_prompt(names, instructions))
    parsed = parse_reply(reply, names)
    return {name: FieldReading(value, confidence) for name, (value, confidence) in parsed.items()}


def is_configured(provider=None):
    """True when the provider has what it needs (keys and models, or sample mode)."""
    try:
        get_provider(provider).check_configured()
    except OcrUnavailable:
        return False
    return True


def extract(image_bytes, *, fields=None, provider=None, instructions=""):
    """Read a form image, trying each configured model in order.

    Raises OcrUnavailable when nothing can answer; callers must then offer manual
    entry so OCR never blocks the workflow.
    """
    names = _field_names(fields)
    provider = get_provider(provider)
    provider.check_configured()
    try:
        image, mime = prepare_image(image_bytes)
    except OcrProviderError as error:
        raise OcrUnavailable(str(error)) from error
    attempts = []
    for model in provider.models():
        try:
            readings = _read_with_model(provider, model, image, mime, names, instructions)
        except OcrProviderError as error:
            logger.warning("OCR model %s failed: %s", model, error)
            attempts.append((model, str(error)))
            continue
        return OcrResult(readings, provider.name, model, attempts)
    detail = "; ".join(f"{model}: {why}" for model, why in attempts)
    raise OcrUnavailable(f"No OCR model could read the form ({detail}).")


def extract_with_model(image_bytes, model, *, fields=None, provider=None):
    """Ask exactly one model, with no fallback; used to compare models."""
    names = _field_names(fields)
    provider = get_provider(provider)
    provider.check_configured()
    image, mime = prepare_image(image_bytes)
    readings = _read_with_model(provider, model, image, mime, names)
    return OcrResult(readings, provider.name, model)
