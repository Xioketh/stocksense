"""Unit tests: pure functions, no database, no HTTP. These run in milliseconds."""

import pytest

from app.services.stock_rules import apply_sale, is_low_stock


def test_is_low_stock_when_below_threshold():
    assert is_low_stock(qty=4, threshold=5) is True


def test_is_not_low_stock_when_equal_to_threshold():
    # "below" means strictly less than, so 5 with a limit of 5 is still OK
    assert is_low_stock(qty=5, threshold=5) is False


def test_threshold_zero_never_alerts():
    assert is_low_stock(qty=0, threshold=0) is False


# parametrize runs the same test with different inputs
@pytest.mark.parametrize(
    ("current", "sold", "expected"),
    [(20, 16, 4), (10, 10, 0), (5, 1, 4)],
)
def test_apply_sale_reduces_stock(current, sold, expected):
    assert apply_sale(current, sold) == expected


def test_apply_sale_rejects_selling_more_than_available():
    with pytest.raises(ValueError, match="not enough stock"):
        apply_sale(current_qty=3, sold_qty=4)


def test_apply_sale_rejects_zero_or_negative():
    with pytest.raises(ValueError):
        apply_sale(current_qty=10, sold_qty=0)