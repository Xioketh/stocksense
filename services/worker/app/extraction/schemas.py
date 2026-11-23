"""What we ASK Gemini for, and what we ACCEPT from it.

Two sets of models on purpose:
1. GeminiInvoice / GeminiLine: the SHAPE we ask for (sent as the response
   schema). Types and descriptions only, no limits, so any Gemini model
   accepts the schema.
2. InvoiceExtraction / ExtractedLine: OUR rules. Gemini's answer must pass
   these before it can touch stock. Never trust AI output blindly.
"""

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.extraction.base import ExtractionFailed

MAX_LINES = 100  # a small shop's invoice; more than this is almost certainly wrong
MAX_QTY = 10_000  # per line; protects stock from a misread "20" -> "20000"


# ---------- 1. The shape we ask Gemini for ----------


class GeminiLine(BaseModel):
    sku: str | None = Field(
        description="The product code printed on this line, copied exactly. "
        "null if the line has no code."
    )
    name: str = Field(description="The product name or description as printed on this line.")
    quantity: int = Field(description="Number of units delivered on this line (a whole number).")


class GeminiInvoice(BaseModel):
    is_invoice: bool = Field(
        description="true only if the document is a supplier invoice or delivery note "
        "that lists products."
    )
    lines: list[GeminiLine] = Field(
        description="Every product line, in the order printed. Empty if is_invoice is false."
    )


# ---------- 2. What we accept ----------


class ExtractedLine(BaseModel):
    sku: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    qty: int = Field(gt=0, le=MAX_QTY)

    @field_validator("sku")
    @classmethod
    def clean_sku(cls, value: str | None) -> str | None:
        """' rice-5 ' -> 'RICE-5'. An empty code counts as no code."""
        if value is None:
            return None
        return value.strip().upper() or None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()


class InvoiceExtraction(BaseModel):
    lines: list[ExtractedLine] = Field(min_length=1, max_length=MAX_LINES)


def parse_gemini_output(text: str | None) -> InvoiceExtraction:
    """Turn Gemini's raw JSON text into validated lines, or raise ExtractionFailed."""
    if not text:
        raise ExtractionFailed("Gemini returned an empty answer")

    try:
        raw = GeminiInvoice.model_validate_json(text)
    except ValidationError as exc:
        raise ExtractionFailed("Gemini's answer was not in the expected JSON format") from exc

    if not raw.is_invoice:
        raise ExtractionFailed("The file does not look like a supplier invoice")

    # Validate the whole list in ONE call, so an error knows its position
    # ("line 3, qty") instead of only the field name.
    lines = [{"sku": ln.sku, "name": ln.name, "qty": ln.quantity} for ln in raw.lines]
    try:
        return InvoiceExtraction.model_validate({"lines": lines})
    except ValidationError as exc:
        raise ExtractionFailed(f"Invoice lines failed validation: {_first_problem(exc)}") from exc


def _first_problem(exc: ValidationError) -> str:
    """A short, human-readable reason, e.g. 'line 3, qty: Input should be greater than 0'."""
    error = exc.errors()[0]
    location = error["loc"]  # e.g. ('lines', 2, 'qty') or ('lines',)
    if len(location) >= 3 and location[0] == "lines":
        return f"line {location[1] + 1}, {location[2]}: {error['msg']}"
    return error["msg"]