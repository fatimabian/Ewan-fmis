class OcrUnavailable(Exception):
    """OCR cannot answer right now; the caller must fall back to manual entry."""


class OcrProviderError(Exception):
    """One model or provider failed; the next model in the list may still work."""


class OcrQuotaExceeded(OcrUnavailable):
    """The daily scan limit has been used up; manual entry is still available."""


class UploadRejected(Exception):
    """A photo breaks the file rules; the message tells staff exactly which rule."""


class OcrAllModelsFailed(OcrUnavailable):
    """Every configured model failed on the photo; usually a key, model or provider problem."""
