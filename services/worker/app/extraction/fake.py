"""A stand-in for Gemini: no Google Cloud, no cost, always the same answer."""

from app.extraction.schemas import ExtractedLine, InvoiceExtraction

# The supplier invoice from Nimal's user story (Coconut oil is not in his catalog).
NIMAL_INVOICE = InvoiceExtraction(
    lines=[
        ExtractedLine(sku="RICE-5", name="Rice 5kg", qty=20),
        ExtractedLine(sku="SUGAR-1", name="Sugar 1kg", qty=25),
        ExtractedLine(sku="COCO-750", name="Coconut oil 750ml", qty=10),
    ]
)


class FakeExtractor:
    """For local development (docker-compose) and tests.

    Tests can choose the answer (result) or make it fail (error), and check
    what it was called with (calls).
    """

    def __init__(
        self, result: InvoiceExtraction | None = None, error: Exception | None = None
    ) -> None:
        self.result = result or NIMAL_INVOICE
        self.error = error
        self.calls: list[tuple[str, int]] = []  # (mime_type, file size)

    def extract(self, content: bytes, mime_type: str) -> InvoiceExtraction:
        self.calls.append((mime_type, len(content)))
        if self.error is not None:
            raise self.error
        return self.result
