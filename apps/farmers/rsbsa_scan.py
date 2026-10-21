import base64
import json
import logging
import re
from datetime import date
from io import BytesIO

import requests
from django.conf import settings
from PIL import Image, UnidentifiedImageError

from apps.common.constants import ROSARIO_BARANGAYS

from .forms import VALID_ID_CHOICES
from .models import Farmer


logger = logging.getLogger(__name__)

MAX_SCAN_BYTES = 5 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}
PROFILE_FIELDS = (
    "last_name",
    "first_name",
    "middle_name",
    "extension_name",
    "sex",
    "birth_date",
    "place_of_birth",
    "mother_maiden_name",
    "house_lot_purok",
    "street_sitio",
    "barangay",
    "phone_number",
    "civil_status",
    "spouse_name",
    "highest_education",
    "valid_id_type",
    "valid_id_number",
    "philsys_registered",
    "philsys_pcn",
    "philsys_trn",
    "religion",
    "is_indigenous",
    "indigenous_group",
    "is_pwd",
    "is_four_ps",
    "fca_membership",
    "livelihood",
)
ENUM_VALUES = {
    "sex": {value for value, _label in Farmer.SEX_CHOICES},
    "civil_status": {value for value, _label in Farmer.CIVIL_STATUS_CHOICES},
    "livelihood": {value for value, _label in Farmer.LIVELIHOOD_CHOICES},
    "valid_id_type": {value for value, _label in VALID_ID_CHOICES if value},
    "philsys_registered": {"", "True", "False"},
    "is_indigenous": {"", "True", "False"},
    "is_pwd": {"", "True", "False"},
    "is_four_ps": {"", "True", "False"},
}


class RSBSAScanError(Exception):
    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.status = status


def _scan_schema():
    field_properties = {
        name: {
            "type": "string",
            "description": "Exact value visible on the form, or an empty string when absent or unreadable.",
        }
        for name in PROFILE_FIELDS
    }
    return {
        "type": "object",
        "properties": {
            "is_rsbsa_form": {"type": "boolean"},
            "fields": {
                "type": "object",
                "properties": field_properties,
                "required": list(PROFILE_FIELDS),
                "additionalProperties": False,
            },
            "needs_review": {
                "type": "array",
                "items": {"type": "string", "enum": list(PROFILE_FIELDS)},
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["is_rsbsa_form", "fields", "needs_review", "warnings"],
        "additionalProperties": False,
    }


def _scan_prompt():
    barangays = ", ".join(ROSARIO_BARANGAYS)
    valid_ids = ", ".join(sorted(ENUM_VALUES["valid_id_type"]))
    return f"""
Read page 1 of a Philippine RSBSA Enrollment Form 01-2024 and extract only values visibly written or checked on the form.

Rules:
1. Never guess, infer, complete, or correct missing personal information. Use an empty string when a value is absent or unreadable.
2. Set is_rsbsa_form to false if this is not recognizably an RSBSA enrollment form.
3. Add a field name to needs_review whenever handwriting, a checkbox, or a character is uncertain.
4. Dates must be YYYY-MM-DD. Phone numbers must be digits only and, when visible, use Philippine local format 09XXXXXXXXX.
5. Use these exact codes: sex MALE/FEMALE; civil_status SINGLE/MARRIED/WIDOWED/SEPARATED; livelihood FARMER/FARMWORKER/FISHERFOLK/AGRI_YOUTH; Yes/No fields True/False.
6. Barangay must exactly match one Rosario, Batangas barangay when clearly visible: {barangays}.
7. valid_id_type must be empty or one of: {valid_ids}.
8. Do not extract signatures, fingerprints, document images, or an official RSBSA number into any other field.
9. Keep warnings short and useful to the staff reviewer. Do not include hidden reasoning.
""".strip()


def _validated_image(upload):
    if upload.size > MAX_SCAN_BYTES:
        raise RSBSAScanError("Use a JPG, PNG, or WebP image that is 5 MB or smaller.")
    raw = upload.read()
    upload.seek(0)
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image_format = image.format
            width, height = image.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise RSBSAScanError("The selected file is not a readable JPG, PNG, or WebP image.")
    if image_format not in SUPPORTED_IMAGE_TYPES:
        raise RSBSAScanError("Automatic reading supports JPG, PNG, and WebP images only.")
    if width < 900 or height < 900:
        raise RSBSAScanError("Capture a clearer image with at least 900 pixels on each side.")
    return raw, SUPPORTED_IMAGE_TYPES[image_format]


def _response_text(payload):
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
            if content.get("type") == "refusal":
                raise RSBSAScanError(
                    "The form could not be read automatically. Enter the details manually.",
                    status=422,
                )
    raise RSBSAScanError(
        "The form reader returned no usable details. Try a clearer photo.", status=502
    )


def _clean_text(value, limit=250):
    value = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _normalize_fields(raw_fields, needs_review, warnings):
    fields = {name: _clean_text(raw_fields.get(name)) for name in PROFILE_FIELDS}
    review = {name for name in needs_review if name in PROFILE_FIELDS}

    for name, allowed in ENUM_VALUES.items():
        value = fields[name]
        if value not in allowed:
            if value:
                review.add(name)
                warnings.append(f"Review {name.replace('_', ' ')}; the detected value was not valid.")
            fields[name] = ""

    barangay_lookup = {name.casefold(): name for name in ROSARIO_BARANGAYS}
    if fields["barangay"]:
        normalized_barangay = barangay_lookup.get(fields["barangay"].casefold())
        if normalized_barangay:
            fields["barangay"] = normalized_barangay
        else:
            fields["barangay"] = ""
            review.add("barangay")
            warnings.append("The barangay was unclear or is not in the Rosario barangay list.")

    if fields["birth_date"]:
        try:
            parsed_date = date.fromisoformat(fields["birth_date"])
            if parsed_date >= date.today():
                raise ValueError
        except ValueError:
            fields["birth_date"] = ""
            review.add("birth_date")
            warnings.append("The birth date was unclear or invalid.")

    phone_digits = re.sub(r"\D", "", fields["phone_number"])
    if phone_digits.startswith("63") and len(phone_digits) == 12:
        phone_digits = "0" + phone_digits[2:]
    elif phone_digits.startswith("9") and len(phone_digits) == 10:
        phone_digits = "0" + phone_digits
    if phone_digits and not re.fullmatch(r"09\d{9}", phone_digits):
        review.add("phone_number")
        warnings.append("The mobile number was incomplete or unclear.")
        phone_digits = ""
    fields["phone_number"] = phone_digits

    for name in PROFILE_FIELDS:
        try:
            model_field = Farmer._meta.get_field(name)
        except Exception:
            continue
        max_length = getattr(model_field, "max_length", None)
        if max_length and len(fields[name]) > max_length:
            fields[name] = fields[name][:max_length]
            review.add(name)

    unique_warnings = list(dict.fromkeys(_clean_text(item, 180) for item in warnings if item))
    return fields, sorted(review), unique_warnings[:8]


def scan_rsbsa_profile(upload):
    api_key = getattr(settings, "OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RSBSAScanError(
            "Automatic RSBSA reading is not configured yet. Enter the details manually.",
            status=503,
        )

    raw, mime_type = _validated_image(upload)
    image_url = f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}"
    request_payload = {
        "model": settings.RSBSA_OCR_MODEL,
        "store": False,
        "instructions": _scan_prompt(),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Extract the handwritten and checked Farmer Profile values from this RSBSA form page into the required JSON schema.",
                    },
                    {"type": "input_image", "image_url": image_url, "detail": "original"},
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "rsbsa_farmer_profile",
                "strict": True,
                "schema": _scan_schema(),
            }
        },
        "max_output_tokens": 2500,
    }
    try:
        response = requests.post(
            f"{settings.OPENAI_API_BASE.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_payload,
            timeout=settings.RSBSA_OCR_TIMEOUT_SECONDS,
        )
    except requests.Timeout as error:
        raise RSBSAScanError(
            "The form reader took too long. Try again with a clearer photo.", status=504
        ) from error
    except requests.RequestException as error:
        logger.warning("RSBSA form reader request failed: %s", error.__class__.__name__)
        raise RSBSAScanError(
            "The form reader is temporarily unavailable. Enter the details manually or try again later.",
            status=503,
        ) from error

    if response.status_code != 200:
        logger.warning("RSBSA form reader returned HTTP %s", response.status_code)
        raise RSBSAScanError(
            "The form reader could not process this image. Try a clearer photo or enter the details manually.",
            status=502,
        )
    try:
        api_payload = response.json()
        extracted = json.loads(_response_text(api_payload))
    except (ValueError, TypeError) as error:
        raise RSBSAScanError(
            "The form reader returned an invalid result. Try again with a clearer photo.",
            status=502,
        ) from error

    if not extracted.get("is_rsbsa_form"):
        raise RSBSAScanError(
            "This image does not appear to be page 1 of an RSBSA enrollment form.",
            status=422,
        )
    fields, review, warnings = _normalize_fields(
        extracted.get("fields", {}),
        extracted.get("needs_review", []),
        extracted.get("warnings", []),
    )
    if not any(fields.values()):
        raise RSBSAScanError(
            "No readable profile details were found. Retake the photo in brighter light and keep the whole page visible.",
            status=422,
        )
    return {"fields": fields, "needs_review": review, "warnings": warnings}
