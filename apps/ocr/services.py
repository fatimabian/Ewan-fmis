import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .conf import ocr_setting
from .exceptions import OcrAllModelsFailed, OcrProviderError, OcrQuotaExceeded, OcrUnavailable
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
    pages: int = 1
    unreadable_pages: list = field(default_factory=list)


def reserve_photos(count=1):
    """Count photos against today's cap; return False when they do not all fit."""
    limit = ocr_setting("DAILY_LIMIT")
    with transaction.atomic():
        OcrDailyUsage.objects.get_or_create(date=timezone.localdate())
        return bool(
            OcrDailyUsage.objects.filter(date=timezone.localdate(), count__lte=limit - count).update(
                count=F("count") + count
            )
        )


def requests_left_today():
    """How many photos can still be read today."""
    used = (
        OcrDailyUsage.objects.filter(date=timezone.localdate()).values_list("count", flat=True).first()
        or 0
    )
    return max(0, ocr_setting("DAILY_LIMIT") - used)


def _field_names(fields):
    return list(fields or ocr_setting("FIELDS"))


def _read_with_model(provider, model, image, mime, names, instructions=""):
    """Ask one model and return parsed readings."""
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


def _read_page(provider, image, mime, names, instructions):
    """Try each model in order on one photo; return (readings, model, failed attempts)."""
    attempts = []
    for model in provider.models():
        try:
            return _read_with_model(provider, model, image, mime, names, instructions), model, attempts
        except OcrProviderError as error:
            logger.warning("OCR model %s failed: %s", model, error)
            attempts.append((model, str(error)))
    return None, "", attempts


def _merge(pages, names):
    """Per field, keep the reading that has a value and the higher confidence."""
    merged = {}
    for name in names:
        candidates = [page[name] for page in pages]
        merged[name] = max(candidates, key=lambda reading: (bool(reading.value), reading.confidence))
    return merged


def extract_many(images, *, fields=None, provider=None, instructions=""):
    """Read every photo (page) of one form and merge the readings.

    Each photo counts once against the daily limit, however many models are tried.
    Raises OcrUnavailable when nothing can answer, so callers can fall back to manual entry.
    """
    names = _field_names(fields)
    provider = get_provider(provider)
    provider.check_configured()
    prepared = []
    for raw in images:
        try:
            prepared.append(prepare_image(raw))
        except OcrProviderError as error:
            raise OcrUnavailable(str(error)) from error
    if provider.name != "sample" and not reserve_photos(len(prepared)):
        raise OcrQuotaExceeded(
            f"The daily limit of {ocr_setting('DAILY_LIMIT')} scanned photos has been reached. Try again tomorrow."
        )
    readings, models, attempts, unreadable = [], [], [], []
    for number, (image, mime) in enumerate(prepared, start=1):
        page, model, failed = _read_page(provider, image, mime, names, instructions)
        attempts += failed
        if page is None:
            unreadable.append(number)
            continue
        readings.append(page)
        models.append(model)
    if not readings:
        detail = "; ".join(f"{model}: {why}" for model, why in attempts)
        raise OcrAllModelsFailed(f"No OCR model could read the form ({detail}).")
    return OcrResult(_merge(readings, names), provider.name, models[0], attempts, len(prepared), unreadable)


def extract(image_bytes, *, fields=None, provider=None, instructions=""):
    """Read a single photo of a form (see extract_many)."""
    return extract_many([image_bytes], fields=fields, provider=provider, instructions=instructions)


def extract_with_model(image_bytes, model, *, fields=None, provider=None):
    """Ask exactly one model, with no fallback; used to compare models."""
    names = _field_names(fields)
    provider = get_provider(provider)
    provider.check_configured()
    image, mime = prepare_image(image_bytes)
    if provider.name != "sample" and not reserve_photos(1):
        raise OcrQuotaExceeded(f"The daily limit of {ocr_setting('DAILY_LIMIT')} scanned photos has been reached.")
    readings = _read_with_model(provider, model, image, mime, names)
    return OcrResult(readings, provider.name, model)
