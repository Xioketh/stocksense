"""The contract every invoice extractor follows, and the two ways it can fail.

The worker only talks to this small interface, so tests (and local
development) can swap the real Gemini extractor for a fake one.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.extraction.schemas import InvoiceExtraction


class ExtractionFailed(Exception):
    """PERMANENT: trying the same file again will not help.

    Examples: Gemini's answer fails validation, the file isn't an invoice,
    Gemini rejects the file (400). The worker marks the invoice 'failed'
    and acknowledges the message.
    """


class ExtractionUnavailable(Exception):
    """TEMPORARY: the same request may work later.

    Examples: timeout, 429 (busy), 5xx, or a configuration problem
    (403/404) that someone can fix. The worker answers 503, so Pub/Sub
    redelivers the message later with backoff.
    """


class InvoiceExtractor(Protocol):
    def extract(self, content: bytes, mime_type: str) -> "InvoiceExtraction":
        """Read one invoice file and return its validated product lines.

        Raises ExtractionFailed or ExtractionUnavailable.
        """
        ...
