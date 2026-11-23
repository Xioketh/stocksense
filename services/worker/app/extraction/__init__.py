"""Invoice extraction: turn an invoice file into validated product lines.

Same pattern as the API's upload signer: one small interface
(InvoiceExtractor), a real implementation (GeminiExtractor) and a fake one
(FakeExtractor), chosen by the EXTRACTOR_BACKEND setting.
"""

import logging
from functools import lru_cache

from app.config import get_settings
from app.extraction.base import ExtractionFailed, ExtractionUnavailable, InvoiceExtractor
from app.extraction.fake import FakeExtractor
from app.extraction.gemini import GeminiExtractor, build_client
from app.extraction.schemas import ExtractedLine, InvoiceExtraction

__all__ = [
    "ExtractedLine",
    "ExtractionFailed",
    "ExtractionUnavailable",
    "InvoiceExtraction",
    "InvoiceExtractor",
    "get_extractor",
]

logger = logging.getLogger(__name__)


@lru_cache
def get_extractor() -> InvoiceExtractor:
    """Build the extractor once, on first use (FastAPI dependency)."""
    settings = get_settings()

    if settings.extractor_backend == "fake":
        # Safety net: a forgotten env var on Cloud Run must fail loudly,
        # not quietly add made-up stock.
        if settings.app_env in ("dev", "prod"):
            raise RuntimeError("EXTRACTOR_BACKEND=fake is not allowed when APP_ENV is dev/prod")
        logger.warning("using FAKE invoice extractor (local/test only)")
        return FakeExtractor()

    if not settings.google_cloud_project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT must be set when EXTRACTOR_BACKEND=gemini")

    logger.info(
        "using Gemini invoice extractor",
        extra={"model": settings.gemini_model, "location": settings.gemini_location},
    )
    client = build_client(
        project=settings.google_cloud_project,
        location=settings.gemini_location,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_attempts=settings.gemini_max_attempts,
    )
    return GeminiExtractor(client, settings.gemini_model, settings.gemini_thinking_level)
