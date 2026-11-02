import base64
import hashlib
import json

import requests

from .conf import ocr_setting
from .exceptions import OcrProviderError, OcrUnavailable


class BaseProvider:
    """A provider turns (model, image, prompt) into the raw text the model replied."""

    name = ""

    def models(self):
        return list(ocr_setting("MODELS"))

    def check_configured(self):
        raise NotImplementedError

    def read(self, model, image, mime, prompt):
        raise NotImplementedError

    @staticmethod
    def _post(url, headers, payload):
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=ocr_setting("TIMEOUT_SECONDS")
            )
        except requests.Timeout as error:
            raise OcrProviderError("The provider timed out.") from error
        except requests.RequestException as error:
            raise OcrProviderError("The provider could not be reached.") from error
        if response.status_code != 200:
            raise OcrProviderError(f"The provider answered HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as error:
            raise OcrProviderError("The provider reply was not JSON.") from error


class OpenRouterProvider(BaseProvider):
    name = "openrouter"

    def check_configured(self):
        if not ocr_setting("OPENROUTER_API_KEY") or not self.models():
            raise OcrUnavailable("OpenRouter is not configured (key or model list missing).")

    def read(self, model, image, mime, prompt):
        encoded = base64.b64encode(image).decode("ascii")
        body = self._post(
            f"{ocr_setting('OPENROUTER_BASE_URL').rstrip('/')}/chat/completions",
            {
                "Authorization": f"Bearer {ocr_setting('OPENROUTER_API_KEY')}",
                "Content-Type": "application/json",
            },
            {
                "model": model,
                "temperature": 0,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            },
                        ],
                    }
                ],
            },
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise OcrProviderError("The provider reply had no message.") from error
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content


class GeminiProvider(BaseProvider):
    name = "gemini"

    def check_configured(self):
        if not ocr_setting("GEMINI_API_KEY") or not self.models():
            raise OcrUnavailable("Gemini is not configured (key or model list missing).")

    def read(self, model, image, mime, prompt):
        encoded = base64.b64encode(image).decode("ascii")
        body = self._post(
            f"{ocr_setting('GEMINI_BASE_URL').rstrip('/')}/models/{model}:generateContent",
            # The key travels in a header, never in the URL, so it stays out of logs.
            {"x-goog-api-key": ocr_setting("GEMINI_API_KEY"), "Content-Type": "application/json"},
            {
                "contents": [
                    {"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": encoded}}]}
                ],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
        )
        try:
            parts = body["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as error:
            raise OcrProviderError("The provider reply had no candidates.") from error
        return "".join(part.get("text", "") for part in parts)


# Canned readings for demos and tests. One is chosen from the image bytes so the
# same photo always gives the same scenario. Coordinates are deliberately wrong
# in several of them to show each validation rule.
SAMPLE_SCENARIOS = (
    {  # clean
        "farmer_name": ("Dela Cruz, Juan", 0.96), "barangay": ("Bulihan", 0.94), "latitude": ("13.7967", 0.93),
        "longitude": ("121.2351", 0.93), "area_hectares": ("1.5", 0.92),
        "commodity": ("Rice", 0.95), "ownership_type": ("OWNED", 0.9),
    },
    {  # latitude and longitude swapped
        "farmer_name": ("Santos, Maria", 0.95), "barangay": ("Namuco", 0.91), "latitude": ("121.2036", 0.88),
        "longitude": ("13.8382", 0.88), "area_hectares": ("0.8", 0.9),
        "commodity": ("Banana", 0.9), "ownership_type": ("TENANT", 0.85),
    },
    {  # missing decimal points
        "farmer_name": ("Reyes, Pedro", 0.93), "barangay": ("Alupay", 0.92), "latitude": ("138404", 0.82),
        "longitude": ("1212922", 0.82), "area_hectares": ("2", 0.9),
        "commodity": ("Coconut", 0.9), "ownership_type": ("OWNED", 0.9),
    },
    {  # degrees, minutes, seconds
        "farmer_name": ("Garcia, Ana", 0.95), "barangay": ("San Isidro", 0.9), "latitude": ("13°48'26.6\"N", 0.86),
        "longitude": ("121°18'54.7\"E", 0.86), "area_hectares": ("1.2", 0.88),
        "commodity": ("Corn", 0.9), "ownership_type": ("LEASED", 0.8),
    },
    {  # outside Rosario
        "farmer_name": ("Lopez, Jose", 0.94), "barangay": ("Mabato", 0.9), "latitude": ("14.5995", 0.9),
        "longitude": ("120.9842", 0.9), "area_hectares": ("1", 0.9),
        "commodity": ("Rice", 0.9), "ownership_type": ("OTHER", 0.8),
    },
    {  # low confidence handwriting
        "farmer_name": ("Bautista, Rosa", 0.55), "barangay": ("Maligaya", 0.6), "latitude": ("13.8182", 0.5),
        "longitude": ("121.2742", 0.52), "area_hectares": ("1.0", 0.45),
        "commodity": ("Mango", 0.7), "ownership_type": ("OWNED", 0.7),
    },
)


# Made-up RSBSA profile readings, used when the prompt asks for profile fields.
SAMPLE_PROFILES = (
    {  # clean
        "form_title": ("RSBSA Enrollment Form", 0.97), "last_name": ("Dela Cruz", 0.95), "first_name": ("Juan", 0.96),
        "middle_name": ("Santos", 0.9), "sex": ("MALE", 0.95), "birth_date": ("1980-05-17", 0.9),
        "place_of_birth": ("Rosario, Batangas", 0.88), "mother_maiden_name": ("Maria Reyes", 0.85),
        "barangay": ("Bulihan", 0.93), "phone_number": ("09171234567", 0.9), "civil_status": ("MARRIED", 0.9),
        "livelihood": ("FARMER", 0.94), "philsys_registered": ("False", 0.8),
    },
    {  # unsure handwriting and a wrong date format
        "form_title": ("RSBSA Enrollment Form", 0.95), "last_name": ("Bautista", 0.55), "first_name": ("Rosa", 0.9),
        "sex": ("FEMALE", 0.95), "birth_date": ("17/05/1975", 0.5), "barangay": ("Maligaya", 0.6),
        "phone_number": ("9181234567", 0.7), "civil_status": ("WIDOWED", 0.8), "livelihood": ("FARMER", 0.9),
    },
)


class SampleProvider(BaseProvider):
    name = "sample"

    def models(self):
        return ["sample"]

    def check_configured(self):
        return None

    def read(self, model, image, mime, prompt):
        scenarios = SAMPLE_PROFILES if '"last_name"' in prompt else SAMPLE_SCENARIOS
        scenario = scenarios[int(hashlib.sha256(image).hexdigest(), 16) % len(scenarios)]
        return json.dumps(
            {"fields": {k: {"value": v, "confidence": c} for k, (v, c) in scenario.items()}}
        )


PROVIDERS = {cls.name: cls for cls in (OpenRouterProvider, GeminiProvider, SampleProvider)}


def get_provider(name=None):
    """Return the configured provider instance or raise OcrUnavailable."""
    name = (name or ocr_setting("PROVIDER")).lower()
    if name not in PROVIDERS:
        raise OcrUnavailable(f"Unknown OCR provider '{name}'.")
    return PROVIDERS[name]()
