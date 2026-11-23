"""Match extracted invoice lines to products. Pure logic: no database, no AI.

Version 1 rule (Decision 1): a line matches ONLY if its SKU is exactly a
product's SKU. Anything else is 'needs_review' for a human. A missed match
costs Nimal a minute; a wrong match silently corrupts his stock.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.extraction import ExtractedLine


@dataclass(frozen=True)
class MatchedLine:
    line_no: int  # 1, 2, 3... position on the invoice
    sku: str | None
    name: str
    qty: int
    product_id: int | None

    @property
    def status(self) -> str:
        return "matched" if self.product_id is not None else "needs_review"


def match_lines(
    lines: Sequence[ExtractedLine], product_ids_by_sku: Mapping[str, int]
) -> list[MatchedLine]:
    """Number the lines and look each SKU up. SKUs are already cleaned (uppercase)."""
    return [
        MatchedLine(
            line_no=number,
            sku=line.sku,
            name=line.name,
            qty=line.qty,
            product_id=product_ids_by_sku.get(line.sku) if line.sku else None,
        )
        for number, line in enumerate(lines, start=1)
    ]
