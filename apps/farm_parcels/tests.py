from io import BytesIO
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from .geocamera import extract_geocamera_metadata, reconcile_geotagged_photos


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
