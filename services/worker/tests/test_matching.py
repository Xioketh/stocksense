"""Unit tests for matching: pure logic, no database."""

from app.extraction import ExtractedLine
from app.services.matching import match_lines

CATALOG = {"RICE-5": 1, "SUGAR-1": 2}  # sku -> product id


def test_exact_sku_matches_and_everything_else_needs_review():
    lines = [
        ExtractedLine(sku="RICE-5", name="Rice 5kg", qty=20),
        ExtractedLine(sku="COCO-750", name="Coconut oil", qty=10),  # not sold here
        ExtractedLine(sku=None, name="Basmati rice 1kg", qty=8),  # no code printed
    ]

    result = match_lines(lines, CATALOG)

    assert [(m.line_no, m.product_id, m.status) for m in result] == [
        (1, 1, "matched"),
        (2, None, "needs_review"),
        (3, None, "needs_review"),
    ]


def test_similar_sku_is_not_a_match():
    # "RICE-10" looks like "RICE-5" but is a different product: never guess.
    result = match_lines([ExtractedLine(sku="RICE-10", name="Rice 10kg", qty=2)], CATALOG)

    assert result[0].status == "needs_review"
