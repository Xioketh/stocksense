"""Pure business rules: no database, no HTTP. Easy to unit test."""


def is_low_stock(qty: int, threshold: int) -> bool:
    """Stock is low when it falls BELOW the threshold (e.g. 4 < 5).

    A threshold of 0 means "never alert".
    """
    return qty < threshold


def apply_sale(current_qty: int, sold_qty: int) -> int:
    """Return the new quantity after a sale, or raise if there isn't enough stock."""
    if sold_qty <= 0:
        raise ValueError("sold_qty must be positive")
    if sold_qty > current_qty:
        raise ValueError(f"not enough stock: have {current_qty}, tried to sell {sold_qty}")
    return current_qty - sold_qty
