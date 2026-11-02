import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ocr.conf import ocr_setting
from apps.ocr.exceptions import OcrProviderError, OcrUnavailable
from apps.ocr.providers import get_provider
from apps.ocr.services import extract_with_model


class Command(BaseCommand):
    help = "Run every configured OCR model on sample form images and print the readings side by side."

    def add_arguments(self, parser):
        parser.add_argument("images", nargs="+", help="Paths to dummy or consented form images.")
        parser.add_argument("--models", help="Comma separated model names; defaults to OCR_MODELS.")
        parser.add_argument("--provider", help="openrouter, gemini or sample; defaults to OCR_PROVIDER.")

    def handle(self, *args, **options):
        try:
            provider = get_provider(options["provider"])
            provider.check_configured()
        except OcrUnavailable as error:
            raise CommandError(str(error))
        models = (
            [m.strip() for m in options["models"].split(",") if m.strip()]
            if options["models"]
            else provider.models()
        )
        self.stdout.write(
            f"Provider {provider.name}; confidence threshold {ocr_setting('CONFIDENCE_THRESHOLD')}. "
            "Images are sent to an outside provider: use dummy or consented forms only."
        )
        for path in options["images"]:
            raw = Path(path).read_bytes()
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{path}"))
            for model in models:
                started = time.monotonic()
                try:
                    result = extract_with_model(raw, model, provider=provider.name)
                except (OcrProviderError, OcrUnavailable) as error:
                    self.stdout.write(self.style.ERROR(f"  {model}: FAILED ({error})"))
                    continue
                seconds = time.monotonic() - started
                self.stdout.write(self.style.SUCCESS(f"  {model}: {seconds:.1f}s"))
                for name, reading in result.fields.items():
                    self.stdout.write(f"    {name:15} {reading.value!r:32} {reading.confidence:.2f}")
