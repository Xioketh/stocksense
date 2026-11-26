"""Database operations for products and stock. Routers call these functions."""

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.events import EventPublisher, LowStockEvent
from app.models import Product, StockMovement
from app.schemas import ProductCreate, StockOutResponse
from app.services.stock_rules import apply_sale, crossed_into_low_stock, is_low_stock

logger = logging.getLogger(__name__)
LOW_STOCK_SQL = Product.qty < Product.low_stock_threshold


def create_product(db: Session, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError:
        # The UNIQUE constraint on sku failed: the SKU already exists.
        db.rollback()
        raise ConflictError(f"Product with SKU '{data.sku}' already exists")
    db.refresh(product)
    logger.info("product created", extra={"sku": product.sku, "qty": product.qty})
    return product


def list_products(
    db: Session, limit: int, offset: int, low_stock: bool | None = None
) -> tuple[list[Product], int]:
    """low_stock: None = all products, True = only low, False = only OK."""
    query = select(Product)
    count_query = select(func.count()).select_from(Product)
    if low_stock is not None:
        condition = LOW_STOCK_SQL if low_stock else ~LOW_STOCK_SQL
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    items = db.scalars(query.order_by(Product.id).limit(limit).offset(offset)).all()
    return list(items), total


def get_product_by_sku(db: Session, sku: str) -> Product:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise NotFoundError(f"Product with SKU '{sku}' not found")
    return product


def record_sale(db: Session, sku: str, qty: int, publisher: EventPublisher) -> StockOutResponse:
    # with_for_update() locks this product row until we commit.
    # If two sales for the same product arrive at the same time,
    # the second one waits, so stock can't be counted wrong.
    # (It also means only ONE of them can see the "OK -> low" crossing.)
    product = db.scalar(select(Product).where(Product.sku == sku).with_for_update())
    if product is None:
        raise NotFoundError(f"Product with SKU '{sku}' not found")

    old_qty = product.qty
    try:
        product.qty = apply_sale(old_qty, qty)
    except ValueError as exc:
        db.rollback()  # release the row lock
        raise ConflictError(str(exc))

    # The quantity change and the audit record are saved in ONE transaction:
    # either both are saved or neither is.
    db.add(StockMovement(product_id=product.id, change=-qty, reason="sale"))
    db.commit()

    logger.info(
        "sale recorded",
        extra={"sku": sku, "sold": qty, "old_qty": old_qty, "new_qty": product.qty},
    )

    # Publish only AFTER the commit: never announce a sale that was rolled back.
    if crossed_into_low_stock(old_qty, product.qty, product.low_stock_threshold):
        _announce_low_stock(publisher, product)

    low = is_low_stock(product.qty, product.low_stock_threshold)
    return StockOutResponse(sku=sku, old_qty=old_qty, new_qty=product.qty, low_stock=low)


def _announce_low_stock(publisher: EventPublisher, product: Product) -> None:
    """Publish a LowStock event. A failure here must NOT fail the sale.

    The sale is already committed. If we returned 500 now, the client would
    think the sale failed and might send it again -> stock reduced twice.
    So we log the failure (an alert watches for this log) and still return 200.
    """
    event = LowStockEvent(
        sku=product.sku,
        name=product.name,
        qty=product.qty,
        threshold=product.low_stock_threshold,
    )
    log = {"sku": event.sku, "qty": event.qty, "threshold": event.threshold}
    try:
        message_id = publisher.publish_low_stock(event)
    except Exception:
        logger.exception(
            "low stock event NOT published",
            extra={**log, "event": "low_stock_publish_failed", "event_id": event.event_id},
        )
        return
    logger.warning(
        "low stock",
        extra={
            **log,
            "event": "low_stock_published",
            "event_id": event.event_id,
            "message_id": message_id,
        },
    )
