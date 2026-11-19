"""Database operations for products and stock. Routers call these functions."""

import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import Product, StockMovement
from app.schemas import ProductCreate, StockOutResponse
from app.services.stock_rules import apply_sale, is_low_stock

logger = logging.getLogger(__name__)


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


def list_products(db: Session, limit: int, offset: int) -> tuple[list[Product], int]:
    total = db.scalar(select(func.count()).select_from(Product)) or 0
    items = db.scalars(select(Product).order_by(Product.id).limit(limit).offset(offset)).all()
    return list(items), total


def get_product_by_sku(db: Session, sku: str) -> Product:
    product = db.scalar(select(Product).where(Product.sku == sku))
    if product is None:
        raise NotFoundError(f"Product with SKU '{sku}' not found")
    return product


def record_sale(db: Session, sku: str, qty: int) -> StockOutResponse:
    # with_for_update() locks this product row until we commit.
    # If two sales for the same product arrive at the same time,
    # the second one waits, so stock can't be counted wrong.
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

    low = is_low_stock(product.qty, product.low_stock_threshold)
    logger.info(
        "sale recorded",
        extra={"sku": sku, "sold": qty, "old_qty": old_qty, "new_qty": product.qty},
    )
    if low:
        # Phase 5: publish a "LowStock" event to Pub/Sub here.
        logger.warning(
            "low stock",
            extra={"sku": sku, "qty": product.qty, "threshold": product.low_stock_threshold},
        )

    return StockOutResponse(sku=sku, old_qty=old_qty, new_qty=product.qty, low_stock=low)
