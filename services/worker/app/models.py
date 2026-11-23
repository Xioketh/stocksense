"""The worker's view of the shared database.

The API OWNS the schema: its Alembic migrations create and change these
tables. Here we map only the columns the worker reads or writes, so the
worker never runs migrations and can't accidentally change the schema.
(Columns not listed here, like created_at, get their database defaults.)
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    qty: Mapped[int] = mapped_column(Integer)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    gcs_path: Mapped[str] = mapped_column(String(300), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(String(500))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    line_no: Mapped[int] = mapped_column(Integer)
    raw_sku: Mapped[str | None] = mapped_column(String(64))
    raw_name: Mapped[str] = mapped_column(String(200))
    qty: Mapped[int] = mapped_column(Integer)
    matched_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    status: Mapped[str] = mapped_column(String(20))


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    change: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(20))
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    invoice_item_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_items.id"))
