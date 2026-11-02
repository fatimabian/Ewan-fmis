import json
from io import BytesIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from . import services
from .exceptions import OcrProviderError, OcrUnavailable
from .models import OcrDailyUsage
from .parsing import parse_reply

FIELDS = ["farmer_name", "latitude"]


def image_bytes(color=(200, 200, 200)):
    buffer = BytesIO()
    Image.new("RGB", (900, 1200), color).save(buffer, format="PNG")
    return buffer.getvalue()


def reply(value="Juan", confidence=0.9):
    return json.dumps(
        {"fields": {"farmer_name": {"value": value, "confidence": confidence},
                    "latitude": {"value": "13.8", "confidence": 0.8}}}
    )


def openrouter_response(text):
    response = mock.Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": text}}]}
    return response


OPENROUTER = {"PROVIDER": "openrouter", "OPENROUTER_API_KEY": "k", "MODELS": ["m1", "m2", "m3"], "DAILY_LIMIT": 5}


@override_settings(OCR=OPENROUTER)
class FallbackTests(TestCase):
    @mock.patch("apps.ocr.providers.requests.post")
    def test_first_model_answers(self, post):
        post.return_value = openrouter_response(reply())
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m1")
        self.assertEqual(result.fields["farmer_name"].value, "Juan")
        self.assertEqual(result.fields["farmer_name"].confidence, 0.9)
        self.assertEqual(post.call_count, 1)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_falls_back_when_a_model_errors_or_returns_garbage(self, post):
        failure = mock.Mock(status_code=429)
        post.side_effect = [failure, openrouter_response("not json"), openrouter_response(reply())]
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m3")
        self.assertEqual(len(result.attempts), 2)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_all_models_failing_raises_unavailable(self, post):
        post.return_value = mock.Mock(status_code=500)
        with self.assertRaises(OcrUnavailable):
            services.extract(image_bytes(), fields=FIELDS)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_daily_limit_stops_requests(self, post):
        post.return_value = mock.Mock(status_code=500)
        for _ in range(2):
            with self.assertRaises(OcrUnavailable):
                services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(OcrDailyUsage.objects.get().count, 5)
        self.assertEqual(post.call_count, 5)
        self.assertEqual(services.requests_left_today(), 0)

    @mock.patch("apps.ocr.providers.requests.post", side_effect=__import__("requests").Timeout)
    def test_timeout_is_handled(self, post):
        with self.assertRaises(OcrUnavailable):
            services.extract(image_bytes(), fields=FIELDS)

    def test_unreadable_image_is_unavailable(self):
        with self.assertRaises(OcrUnavailable):
            services.extract(b"not an image", fields=FIELDS)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_image_is_reencoded_without_exif(self, post):
        post.return_value = openrouter_response(reply())
        services.extract(image_bytes(), fields=FIELDS)
        sent = post.call_args.kwargs["json"]["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(sent.startswith("data:image/jpeg;base64,"))
        self.assertNotIn("Authorization", json.dumps(post.call_args.kwargs["json"]))


class ConfigurationTests(TestCase):
    @override_settings(OCR={**OPENROUTER, "OPENROUTER_API_KEY": ""})
    def test_missing_key_is_unavailable_without_network(self):
        with mock.patch("apps.ocr.providers.requests.post") as post:
            with self.assertRaises(OcrUnavailable):
                services.extract(image_bytes(), fields=FIELDS)
        post.assert_not_called()

    @override_settings(OCR={**OPENROUTER, "MODELS": []})
    def test_missing_models_is_unavailable(self):
        with self.assertRaises(OcrUnavailable):
            services.extract(image_bytes(), fields=FIELDS)

    @override_settings(OCR={**OPENROUTER, "PROVIDER": "nope"})
    def test_unknown_provider(self):
        with self.assertRaises(OcrUnavailable):
            services.extract(image_bytes(), fields=FIELDS)


class GeminiProviderTests(TestCase):
    @override_settings(OCR={"PROVIDER": "gemini", "GEMINI_API_KEY": "g", "MODELS": ["gem-a"], "DAILY_LIMIT": 5})
    @mock.patch("apps.ocr.providers.requests.post")
    def test_gemini_request_and_reply(self, post):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": reply("Ana")}]}}]}
        post.return_value = response
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual((result.provider, result.model), ("gemini", "gem-a"))
        self.assertEqual(result.fields["farmer_name"].value, "Ana")
        url = post.call_args.args[0]
        self.assertIn("models/gem-a:generateContent", url)
        self.assertNotIn("key=", url)  # the key is in a header, not the URL
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "g")


class SampleProviderTests(TestCase):
    @override_settings(OCR={"PROVIDER": "sample", "DAILY_LIMIT": 1})
    def test_sample_needs_no_key_and_is_deterministic(self):
        first = services.extract(image_bytes((1, 2, 3)))
        second = services.extract(image_bytes((1, 2, 3)))
        self.assertEqual(first.provider, "sample")
        self.assertEqual(first.fields, second.fields)
        self.assertFalse(OcrDailyUsage.objects.exists())


class ParsingTests(TestCase):
    def test_code_fences_and_bare_values(self):
        text = '```json\n{"fields": {"farmer_name": "Juan", "latitude": {"value": "13", "confidence": 7}}}\n```'
        parsed = parse_reply(text, FIELDS)
        self.assertEqual(parsed["farmer_name"], ("Juan", 0.5))
        self.assertEqual(parsed["latitude"], ("13", 1.0))

    def test_empty_value_has_zero_confidence(self):
        parsed = parse_reply('{"fields": {"farmer_name": {"value": "x", "confidence": 1}, "latitude": {"value": "", "confidence": 0.9}}}', FIELDS)
        self.assertEqual(parsed["latitude"], ("", 0.0))

    def test_rejects_unusable_replies(self):
        for bad in ("", "[]", '{"fields": []}', '{"fields": {"farmer_name": {"value": ""}}}'):
            with self.assertRaises(OcrProviderError):
                parse_reply(bad, FIELDS)


class CompareCommandTests(TestCase):
    @override_settings(OCR={"PROVIDER": "sample"})
    def test_runs_on_sample_provider(self):
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder, "form.png")
            path.write_bytes(image_bytes())
            out = BytesIO()
            from io import StringIO
            out = StringIO()
            call_command("ocr_compare", str(path), "--provider", "sample", stdout=out)
        self.assertIn("sample:", out.getvalue())
        self.assertIn("farmer_name", out.getvalue())
