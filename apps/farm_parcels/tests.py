from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
import shutil
import subprocess

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image, ImageDraw, ImageFont
from PIL.TiffImagePlugin import IFDRational

from .geocamera import _stamp_coordinates, extract_geocamera_metadata, reconcile_geotagged_photos


class GeoCameraMetadataTests(SimpleTestCase):
    def _photo(self, pk, latitude, longitude):
        return SimpleNamespace(
            pk=pk,
            gps_latitude=latitude,
            gps_longitude=longitude,
        )

    def test_original_photo_gps_metadata_is_extracted(self):
        image_bytes = BytesIO()
        image = Image.new("RGB", (16, 16), "green")
        exif = Image.Exif()
        exif[36867] = "2026:10:30 08:15:00"
        exif[34853] = {
            1: "N",
            2: (IFDRational(13), IFDRational(50), IFDRational(0)),
            3: "E",
            4: (IFDRational(121), IFDRational(12), IFDRational(0)),
        }
        image.save(image_bytes, format="JPEG", exif=exif)
        upload = SimpleUploadedFile(
            "geo.jpg", image_bytes.getvalue(), content_type="image/jpeg"
        )

        metadata = extract_geocamera_metadata(upload)

        self.assertEqual(metadata["latitude"], 13.8333333)
        self.assertEqual(metadata["longitude"], 121.2)
        self.assertEqual(metadata["source"], "Embedded GPS metadata")
        self.assertEqual(metadata["captured_at"].year, 2026)
        self.assertEqual(len(metadata["file_sha256"]), 64)

    def test_stamp_requires_two_valid_explicit_coordinate_labels(self):
        self.assertEqual(_stamp_coordinates("Latitude : 13.844918\nLongitude : 121.2148175"), (13.844918, 121.2148175))
        self.assertIsNone(_stamp_coordinates("Latitude: 13.844918"))
        self.assertIsNone(_stamp_coordinates("Latitude: 93.844918 Longitude: 121.2148175"))
        self.assertIsNone(_stamp_coordinates("Invoice: 13.844918 Phone: 121.2148175"))

    def test_screenshot_visible_stamp_is_read_locally(self):
        if not shutil.which("tesseract"):
            self.skipTest("Local Tesseract is not installed")
        image = Image.new("RGB", (720, 422), "black")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("DejaVuSans.ttf", 14)
        draw.multiline_text((12, 8), "Republic of the Philippines\nDEPARTMENT OF AGRICULTURE\nLatitude : 13.844918\nLongitude : 121.2148175", font=font, fill="white", spacing=3)
        data = BytesIO()
        image.save(data, format="PNG")
        result = extract_geocamera_metadata(SimpleUploadedFile("screenshot.png", data.getvalue(), content_type="image/png"))
        self.assertEqual(result["latitude"], 13.844918)
        self.assertEqual(result["longitude"], 121.2148175)
        self.assertIn("OCR", result["source"])

    @patch("apps.farm_parcels.geocamera.subprocess.run", side_effect=subprocess.TimeoutExpired("tesseract", 5))
    @patch("apps.farm_parcels.geocamera.shutil.which", return_value="/usr/bin/tesseract")
    def test_stamp_timeout_preserves_photo_without_fabricating_gps(self, _which, _run):
        data = BytesIO()
        Image.new("RGB", (200, 200), "white").save(data, format="PNG")
        upload = SimpleUploadedFile("photo.png", data.getvalue(), content_type="image/png")
        result = extract_geocamera_metadata(upload)
        self.assertIsNone(result["latitude"])
        self.assertEqual(upload.tell(), 0)

    def test_close_coordinates_use_median_and_exclude_distant_outlier(self):
        photos = [
            self._photo(1, 13.8333300, 121.2000000),
            self._photo(2, 13.8333400, 121.2000100),
            self._photo(3, 13.9000000, 121.3000000),
        ]

        summary = reconcile_geotagged_photos(photos)

        self.assertEqual(summary["status"], "ready")
        self.assertEqual(summary["proposed"], (13.833335, 121.200005))
        self.assertEqual(len(summary["accepted"]), 2)
        self.assertEqual(len(summary["outliers"]), 1)

    def test_two_different_locations_are_ambiguous(self):
        photos = [
            self._photo(1, 13.8333300, 121.2000000),
            self._photo(2, 13.9000000, 121.3000000),
        ]

        summary = reconcile_geotagged_photos(photos)

        self.assertEqual(summary["status"], "ambiguous")
        self.assertIsNone(summary["proposed"])
