import json
import re

from .exceptions import OcrProviderError
from .fields import DEFAULT_DESCRIPTION, FIELD_DESCRIPTIONS


def build_prompt(field_names, instructions=""):
    """Prompt shared by every provider so models are compared fairly."""
    lines = "\n".join(
        f'- "{name}": {FIELD_DESCRIPTIONS.get(name, DEFAULT_DESCRIPTION)}' for name in field_names
    )
    return (
        "You read a photographed, possibly handwritten farm registration form from "
        "Rosario, Batangas, Philippines. Copy only what is visibly written.\n"
        + (f"{instructions.strip()}\n" if instructions else "")
        + "Rules:\n"
        "1. Never guess, correct or complete a value. Copy coordinates exactly as written, "
        "even if they look wrong.\n"
        '2. Use an empty string and confidence 0 when a value is absent or unreadable.\n'
        "3. Give each field a confidence from 0 to 1 for how sure you are of the reading.\n"
        "4. Reply with JSON only, shaped as "
        '{"fields": {"<name>": {"value": "<text>", "confidence": <number>}}}.\n'
        f"Fields:\n{lines}"
    )


def _reply_payload(text):
    """Accept complete JSON, including a single JSON answer wrapped in prose or fences.

    Do not repair truncated JSON or guess missing values, and reject ambiguous answers.
    """
    if not isinstance(text, str):
        raise OcrProviderError("The reply was not valid JSON.")
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    candidates, position = [], 0
    while (start := cleaned.find("{", position)) >= 0:
        try:
            candidate, end = decoder.raw_decode(cleaned, start)
        except ValueError:
            position = start + 1
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("fields"), dict):
            candidates.append(candidate)
        position = end
    if len(candidates) != 1:
        raise OcrProviderError("The reply was not valid JSON." if not candidates else "The reply contained multiple conflicting answers.")
    return candidates[0]


def parse_reply(text, field_names):
    """Turn a model reply into {name: (value, confidence)}, or raise OcrProviderError."""
    payload = _reply_payload(text)
    fields = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict):
        raise OcrProviderError("The reply had no fields object.")
    parsed = {}
    for name in field_names:
        entry = fields.get(name)
        if isinstance(entry, dict):
            value, confidence = entry.get("value"), entry.get("confidence")
        else:
            value, confidence = entry, None
        value = re.sub(r"[\x00-\x1f\x7f]", " ", str(value if value is not None else "")).strip()[:250]
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.5 if value else 0.0
        parsed[name] = (value, confidence if value else 0.0)
    if not any(value for value, _ in parsed.values()):
        raise OcrProviderError("The reply contained no readable values.")
    return parsed
