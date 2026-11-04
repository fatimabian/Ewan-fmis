import json
from io import BytesIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from PIL import Image

from . import services
from django.core.files.uploadedfile import SimpleUploadedFile

from .exceptions import OcrProviderError, OcrQuotaExceeded, OcrUnavailable, UploadRejected
from .models import OcrDailyUsage
from .parsing import parse_reply
from .uploads import read_uploads

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
    def setUp(self):
        cache.clear()

    @mock.patch("apps.ocr.providers.requests.post")
    def test_first_model_answers(self, post):
        post.return_value = openrouter_response(reply())
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m1")
        self.assertEqual(result.fields["farmer_name"].value, "Juan")
        self.assertEqual(result.fields["farmer_name"].confidence, 0.9)
        self.assertEqual(post.call_count, 1)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_openrouter_requests_json_and_room_for_complete_registration(self, post):
        post.return_value = openrouter_response(reply())
        services.extract(image_bytes(), fields=FIELDS)
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertGreaterEqual(body["max_tokens"], 4096)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_truncated_provider_answer_is_not_accepted_as_complete(self, post):
        truncated = openrouter_response(reply("Not a complete scan"))
        truncated.json.return_value["choices"][0]["finish_reason"] = "length"
        post.side_effect = [truncated, openrouter_response(reply("Complete answer"))]
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m2")
        self.assertEqual(result.fields["farmer_name"].value, "Complete answer")
        self.assertIn("cut off", result.attempts[0][1])

    @mock.patch("apps.ocr.providers.requests.post")
    def test_malformed_provider_message_falls_back_without_crashing(self, post):
        malformed = openrouter_response(reply())
        malformed.json.return_value["choices"] = [None]
        post.side_effect = [malformed, openrouter_response(reply("Complete answer"))]
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m2")
        self.assertEqual(result.fields["farmer_name"].value, "Complete answer")

    @mock.patch("apps.ocr.providers.requests.post")
    def test_wrapped_json_does_not_exhaust_models_or_daily_photo_quota(self, post):
        post.return_value = openrouter_response("Here is the form:\n```json\n" + reply() + "\n```")
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m1")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(OcrDailyUsage.objects.get().count, 1)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_falls_back_when_a_model_errors_or_returns_garbage(self, post):
        failure = mock.Mock(status_code=429)
        post.side_effect = [failure, openrouter_response("not json"), openrouter_response(reply())]
        result = services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(result.model, "m3")
        self.assertEqual(len(result.attempts), 2)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_last_working_model_is_tried_first_on_the_next_scan(self, post):
        failure = mock.Mock(status_code=429)
        post.side_effect = [failure, openrouter_response(reply("First")), openrouter_response(reply("Second"))]
        first = services.extract(image_bytes((1, 2, 3)), fields=FIELDS)
        second = services.extract(image_bytes((4, 5, 6)), fields=FIELDS)
        self.assertEqual((first.model, second.model), ("m2", "m2"))
        self.assertEqual(post.call_count, 3)
        self.assertEqual(second.fields["farmer_name"].value, "Second")

    @mock.patch("apps.ocr.providers.requests.post")
    def test_all_models_failing_raises_unavailable(self, post):
        post.return_value = mock.Mock(status_code=500)
        with self.assertRaises(OcrUnavailable):
            services.extract(image_bytes(), fields=FIELDS)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_daily_limit_counts_photos_not_model_attempts(self, post):
        post.return_value = mock.Mock(status_code=500)
        for _ in range(5):
            with self.assertRaises(OcrUnavailable):
                services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(post.call_count, 15)  # three models tried for each of five photos
        self.assertEqual(OcrDailyUsage.objects.get().count, 5)
        self.assertEqual(services.requests_left_today(), 0)
        with self.assertRaises(OcrQuotaExceeded):
            services.extract(image_bytes(), fields=FIELDS)
        self.assertEqual(post.call_count, 15)  # no provider call once the limit is reached

    @mock.patch("apps.ocr.providers.requests.post")
    def test_a_batch_that_does_not_fit_is_refused_whole(self, post):
        post.return_value = openrouter_response(reply())
        services.extract_many([image_bytes((1, 1, 1)), image_bytes((2, 2, 2)), image_bytes((3, 3, 3))], fields=FIELDS)
        self.assertEqual(services.requests_left_today(), 2)
        with self.assertRaises(OcrQuotaExceeded):
            services.extract_many([image_bytes((4, 4, 4))] * 3, fields=FIELDS)
        self.assertEqual(services.requests_left_today(), 2)  # nothing was reserved
        self.assertEqual(post.call_count, 3)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_pages_are_merged_by_best_reading(self, post):
        first = json.dumps({"fields": {"farmer_name": {"value": "Juan", "confidence": 0.9}, "latitude": {"value": "", "confidence": 0}}})
        second = json.dumps({"fields": {"farmer_name": {"value": "Juan C", "confidence": 0.6}, "latitude": {"value": "13.8", "confidence": 0.8}}})
        post.side_effect = [openrouter_response(first), openrouter_response(second)]
        result = services.extract_many([image_bytes((1, 1, 1)), image_bytes((2, 2, 2))], fields=FIELDS)
        self.assertEqual((result.fields["farmer_name"].value, result.fields["latitude"].value), ("Juan", "13.8"))
        self.assertEqual((result.pages, result.unreadable_pages), (2, []))
        self.assertEqual(OcrDailyUsage.objects.get().count, 2)

    @mock.patch("apps.ocr.providers.requests.post")
    def test_an_unreadable_page_is_reported_but_others_are_kept(self, post):
        failure = mock.Mock(status_code=500)
        post.side_effect = [openrouter_response(reply()), failure, failure, failure]
        result = services.extract_many([image_bytes((1, 1, 1)), image_bytes((2, 2, 2))], fields=FIELDS)
        self.assertEqual(result.unreadable_pages, [2])
        self.assertEqual(result.fields["farmer_name"].value, "Juan")

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


def upload_file(name="form.png", content=None, size=(900, 1200), color=(200, 200, 200)):
    if content is None:
        buffer = BytesIO()
        Image.new("RGB", size, color).save(buffer, format="PNG")
        content = buffer.getvalue()
    return SimpleUploadedFile(name, content, content_type="image/png")


@override_settings(OCR={"MAX_FILES": 3, "MAX_IMAGE_BYTES": 5 * 1024 * 1024, "DAILY_LIMIT": 30})
class UploadRuleTests(TestCase):
    def reject(self, files, message):
        with self.assertRaises(UploadRejected) as caught:
            read_uploads(files)
        self.assertIn(message, str(caught.exception))

    def test_valid_photos_are_returned_in_order(self):
        contents = read_uploads([upload_file(color=(1, 2, 3)), upload_file("page2.JPG", color=(9, 9, 9))])
        self.assertEqual(len(contents), 2)

    def test_allowed_extensions(self):
        for name in ("a.jpg", "a.JPEG", "a.png", "a.webp"):
            read_uploads([upload_file(name)])
        for name in ("a.gif", "a.pdf", "a.heic", "a", "a.png.exe"):
            self.reject([upload_file(name)], "must be a JPG, JPEG, PNG, WEBP file")

    def test_size_limit_names_the_photo_and_the_limit(self):
        with override_settings(OCR={"MAX_FILES": 3, "MAX_IMAGE_BYTES": 1024 * 1024}):
            big = upload_file(content=b"x" * (2 * 1024 * 1024))
            self.reject([big], "Each photo must be 1 MB or smaller")
            self.reject([upload_file(color=(5, 5, 5)), big], "Photo 2 is 2.0 MB")

    def test_page_limit(self):
        files = [upload_file(color=(i, i, i)) for i in range(4)]
        self.reject(files, "at most 3 photos")
        self.reject([], "Choose at least one photo")

    def test_content_must_be_a_real_image_of_a_good_size(self):
        self.reject([upload_file(content=b"%PDF-1.4 fake")], "not a readable")
        self.reject([upload_file(size=(200, 200))], "too small")

    def test_the_same_photo_twice_is_refused(self):
        photo = upload_file().read()
        self.reject([upload_file(content=photo), upload_file("again.png", content=photo)], "same photo")


class ParsingTests(TestCase):
    def test_code_fences_and_bare_values(self):
        text = '```json\n{"fields": {"farmer_name": "Juan", "latitude": {"value": "13", "confidence": 7}}}\n```'
        parsed = parse_reply(text, FIELDS)
        self.assertEqual(parsed["farmer_name"], ("Juan", 0.5))
        self.assertEqual(parsed["latitude"], ("13", 1.0))

    def test_complete_json_inside_provider_formatting_is_accepted(self):
        payload = reply("Juan {sample}", 0.9)
        for text in (f"Here is the extracted form:\n```json\n{payload}\n```", f"<think>Read only the visible form.</think>\n{payload}"):
            with self.subTest(text=text[:25]):
                self.assertEqual(parse_reply(text, FIELDS)["farmer_name"], ("Juan {sample}", 0.9))

    def test_truncated_and_conflicting_json_answers_are_rejected(self):
        for text in (reply()[:-1], "```json\n" + reply()[:-5], reply("Juan") + "\n" + reply("Pedro")):
            with self.subTest(text=text[:25]), self.assertRaises(OcrProviderError):
                parse_reply(text, FIELDS)

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
