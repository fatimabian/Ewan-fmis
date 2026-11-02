class OcrUnavailable(Exception):
    """OCR cannot answer right now; the caller must fall back to manual entry."""


class OcrProviderError(Exception):
    """One model or provider failed; the next model in the list may still work."""
