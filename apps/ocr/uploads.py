"""File rules for scanned form photos. One place, used by every page that offers Scan & Auto-Fill."""
import hashlib
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from .conf import ocr_setting
from .imaging import ALLOWED_FORMATS
from .exceptions import UploadRejected


ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MIN_SIDE_PIXELS = 400


def max_megabytes():
    """The per file size limit in whole megabytes, as shown to staff."""
    return ocr_setting("MAX_IMAGE_BYTES") // (1024 * 1024)


def read_uploads(files):
    """Validate every photo of one scan by name, size and content; return their bytes.

    Raises UploadRejected naming the photo and the rule it breaks.
    """
    files = list(files)
    limit = ocr_setting("MAX_FILES")
    if not files:
        raise UploadRejected("Choose at least one photo of the form.")
    if len(files) > limit:
        raise UploadRejected(f"A scan can have at most {limit} photos (pages). You added {len(files)}.")
    contents, seen = [], set()
    for number, upload in enumerate(files, start=1):
        label = f"Photo {number}" if len(files) > 1 else "The photo"
        name = (getattr(upload, "name", "") or "").lower()
        if not name.endswith(ALLOWED_EXTENSIONS):
            raise UploadRejected(f"{label} must be a {', '.join(e.upper().lstrip('.') for e in ALLOWED_EXTENSIONS)} file.")
        if upload.size > ocr_setting("MAX_IMAGE_BYTES"):
            raise UploadRejected(f"{label} is {upload.size / (1024 * 1024):.1f} MB. Each photo must be {max_megabytes()} MB or smaller.")
        raw = upload.read()
        try:
            with Image.open(BytesIO(raw)) as image:
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                image_format, width, height = image.format, *image.size
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise UploadRejected(f"{label} is not a readable JPG, PNG or WebP image.")
        if image_format not in ALLOWED_FORMATS:
            raise UploadRejected(f"{label} must be a JPG, PNG or WebP image.")
        if min(width, height) < MIN_SIDE_PIXELS:
            raise UploadRejected(f"{label} is too small. Use one at least {MIN_SIDE_PIXELS} pixels on the short side.")
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen:
            raise UploadRejected(f"{label} is the same photo as an earlier one.")
        seen.add(digest)
        contents.append(raw)
    return contents
