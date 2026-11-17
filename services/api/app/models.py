from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.services.stock_rules import is_low_stock


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("qty >= 0", name="ck_products_qty_non_negative"),
        CheckConstraint("low_stock_threshold >= 0", name="ck_products_threshold_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer, default=0)
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    movements: Mapped[list["StockMovement"]] = relationship(back_populates="product")

    @property
    def is_low_stock(self) -> bool:
        return is_low_stock(self.qty, self.low_stock_threshold)


class StockMovement(Base):
    """Every stock change is recorded here (an audit trail).

    products.qty is the current value; stock_movements explains how we got there.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("reason IN ('sale', 'invoice', 'adjustment')", name="ck_movements_reason"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    change: Mapped[int] = mapped_column(Integer)  # negative for sales, positive for invoices
    reason: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # invoice_id is added in Phase 3 with its own migration, together with the invoices table.

    product: Mapped[Product] = relationship(back_populates="movements")