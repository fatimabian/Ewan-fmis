from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .conf import ocr_setting
from .exceptions import OcrProviderError

ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def prepare_image(raw):
    """Return (jpeg_bytes, mime) with orientation fixed, size capped and EXIF removed."""
    try:
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise OcrProviderError("The image could not be read.") from error
    side = ocr_setting("MAX_IMAGE_SIDE")
    image.thumbnail((side, side))
    output = BytesIO()
    image.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue(), "image/jpeg"
