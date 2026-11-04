"""Read embedded or visibly stamped GPS and propose coordinates for staff review."""

from datetime import datetime
from io import BytesIO
import re
import shutil
import subprocess
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt
from statistics import median

from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError


GEOCAMERA_CLUSTER_METERS = 30.0


def _decimal_degrees(values, reference):
    try:
        degrees, minutes, seconds = (float(value) for value in values)
        coordinate = degrees + minutes / 60 + seconds / 3600
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if str(reference or "").upper() in {"S", "W"}:
        coordinate *= -1
    return coordinate


def _capture_time(exif):
    value = exif.get(36867) or exif.get(306)
    if not value:
        return None
    try:
        captured = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return timezone.make_aware(captured, timezone.get_current_timezone())


def _stamp_coordinates(text):
    """Require both explicit labels; never guess coordinates from other numbers."""
    found = []
    for label, limit in ((r"lat(?:itude)?", 90), (r"lon(?:gitude)?", 180)):
        match = re.search(rf"\b{label}\s*[:=]\s*([+-]?\d{{1,3}}[.,]\d{{4,8}})\b", text, re.I)
        if not match:
            return None
        value = float(match.group(1).replace(",", "."))
        if not -limit <= value <= limit:
            return None
        found.append(round(value, 7))
    return tuple(found)


def _read_gps_stamp(image):
    """Local, bounded OCR of the top stamp; photos never leave the server."""
    executable = shutil.which("tesseract")
    if not executable or min(image.size) < 100:
        return None
    image = ImageOps.exif_transpose(image)
    crop = image.crop((0, 0, image.width, max(1, int(image.height * 0.35))))
    crop.thumbnail((1800, 700))
    scale = min(3, 2400 / crop.width)
    crop = ImageOps.autocontrast(ImageOps.grayscale(crop))
    crop = crop.resize((int(crop.width * scale), int(crop.height * scale)))
    data = BytesIO()
    crop.save(data, format="PNG")
    try:
        response = subprocess.run(
            [executable, "stdin", "stdout", "--psm", "11", "-l", "eng"],
            input=data.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if response.returncode:
        return None
    return _stamp_coordinates(response.stdout.decode("utf-8", errors="replace"))


def extract_geocamera_metadata(upload):
    """Prefer embedded GPS; otherwise propose visible stamp coordinates for review."""
    digest = sha256()
    upload.seek(0)
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    result = {
        "file_sha256": digest.hexdigest(),
        "latitude": None,
        "longitude": None,
        "captured_at": None,
        "source": "Uploaded field photo",
    }
    try:
        with Image.open(upload) as image:
            exif = image.getexif()
            try:
                gps = exif.get_ifd(34853)
            except (AttributeError, KeyError, TypeError, ValueError):
                gps = exif.get(34853) or {}
            latitude = _decimal_degrees(gps.get(2), gps.get(1)) if gps else None
            longitude = _decimal_degrees(gps.get(4), gps.get(3)) if gps else None
            if latitude is not None and longitude is not None:
                if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                    result.update(
                        latitude=round(latitude, 7),
                        longitude=round(longitude, 7),
                        captured_at=_capture_time(exif),
                        source="Embedded GPS metadata",
                    )
            if result["latitude"] is None:
                stamped = _read_gps_stamp(image)
                if stamped:
                    result.update(latitude=stamped[0], longitude=stamped[1], source="Visible GPS stamp (OCR; verify with photo)")
    except (OSError, UnidentifiedImageError, ValueError):
        pass
    finally:
        upload.seek(0)
    return result


def haversine_meters(first, second):
    latitude_1, longitude_1 = (radians(value) for value in first)
    latitude_2, longitude_2 = (radians(value) for value in second)
    latitude_delta = latitude_2 - latitude_1
    longitude_delta = longitude_2 - longitude_1
    value = (
        sin(latitude_delta / 2) ** 2
        + cos(latitude_1) * cos(latitude_2) * sin(longitude_delta / 2) ** 2
    )
    return 6371000 * 2 * asin(sqrt(value))


def reconcile_geotagged_photos(photos, threshold=GEOCAMERA_CLUSTER_METERS):
    """Choose the median of one clear GPS cluster and retain all outliers.

    A coordinate is never used to infer ownership. ``photos`` must already
    belong to the parcel selected by the authenticated staff member.
    """
    points = [
        {
            "photo": photo,
            "point": (float(photo.gps_latitude), float(photo.gps_longitude)),
        }
        for photo in photos
        if photo.gps_latitude is not None and photo.gps_longitude is not None
    ]
    if not points:
        return {
            "status": "missing",
            "message": "No readable GPS coordinates were found in the photo metadata or visible stamp.",
            "points": [],
            "accepted": [],
            "outliers": [],
            "proposed": None,
        }

    clusters = []
    for candidate in points:
        members = [
            item
            for item in points
            if haversine_meters(candidate["point"], item["point"]) <= threshold
        ]
        key = tuple(sorted(item["photo"].pk for item in members))
        if key and all(existing[0] != key for existing in clusters):
            clusters.append((key, members))
    largest_size = max(len(members) for _, members in clusters)
    largest = [members for _, members in clusters if len(members) == largest_size]
    distinct_largest = {
        tuple(sorted(item["photo"].pk for item in members)): members
        for members in largest
    }
    if len(points) > 1 and (largest_size == 1 or len(distinct_largest) > 1):
        return {
            "status": "ambiguous",
            "message": "The photos contain more than one possible field location. Review the images and upload one location at a time.",
            "points": points,
            "accepted": [],
            "outliers": points,
            "proposed": None,
        }

    accepted = next(iter(distinct_largest.values()))
    accepted_ids = {item["photo"].pk for item in accepted}
    outliers = [item for item in points if item["photo"].pk not in accepted_ids]
    proposed = (
        round(median(item["point"][0] for item in accepted), 7),
        round(median(item["point"][1] for item in accepted), 7),
    )
    return {
        "status": "ready",
        "message": (
            f"{len(accepted)} close GPS point(s) support the proposed location."
            + (f" {len(outliers)} distant point(s) were excluded." if outliers else "")
            + (" Some coordinates were read from visible text. Compare every digit with the photo before confirming." if any("OCR" in getattr(item["photo"], "gps_source", "") for item in accepted) else "")
        ),
        "points": points,
        "accepted": accepted,
        "outliers": outliers,
        "proposed": proposed,
    }
