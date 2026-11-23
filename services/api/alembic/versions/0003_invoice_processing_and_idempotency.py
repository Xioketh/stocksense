"""invoice processing lease + idempotency safety nets

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23

Additive only ("expand"), like 0002: new columns and constraints, nothing
renamed or removed. The running app version keeps working while this runs.

invoices:
  - attempts:              how many times a worker started processing it
  - processing_started_at: when the current worker claimed it (a "lease").
                           If a worker crashes, a stale lease can be taken over.
  - CHECKs: a 'processing' invoice must have a lease start time;
            a 'failed' invoice must say why (error_message).

invoice_items:
  - line_no: position on the invoice (1, 2, 3...). UNIQUE per invoice, so the
             same line can never be saved twice.
  - raw_sku: the SKU exactly as read from the invoice (may be missing).
  NOTE: line_no is NOT NULL without a default. That only works because
  invoice_items is still empty in dev and prod (nothing writes to it before
  Phase 4). On a table with rows, this migration would fail loudly instead.

stock_movements:
  - invoice_item_id: which invoice line caused this movement. UNIQUE, so one
    invoice line can increase stock at most ONCE, even if the worker's own
    duplicate checks ever fail. (Postgres allows many NULLs in a UNIQUE
    column, so sales, which have no invoice line, are not affected.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------- invoices ----------
    op.add_column(
        "invoices",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "invoices",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint("ck_invoices_attempts_non_negative", "invoices", "attempts >= 0")
    op.create_check_constraint(
        "ck_invoices_processing_has_lease",
        "invoices",
        "status <> 'processing' OR processing_started_at IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_invoices_failed_has_error",
        "invoices",
        "status <> 'failed' OR error_message IS NOT NULL",
    )

    # ---------- invoice_items ----------
    op.add_column("invoice_items", sa.Column("line_no", sa.Integer(), nullable=False))
    op.add_column("invoice_items", sa.Column("raw_sku", sa.String(length=64), nullable=True))
    op.create_check_constraint("ck_invoice_items_line_no_positive", "invoice_items", "line_no > 0")
    op.create_unique_constraint(
        "uq_invoice_items_invoice_line", "invoice_items", ["invoice_id", "line_no"]
    )

    # ---------- stock_movements ----------
    op.add_column(
        "stock_movements",
        sa.Column(
            "invoice_item_id",
            sa.Integer(),
            sa.ForeignKey("invoice_items.id"),
            nullable=True,
        ),
    )
    op.create_unique_constraint(
        "uq_stock_movements_invoice_item", "stock_movements", ["invoice_item_id"]
    )
    # Same pattern as ck_movements_invoice_link: 'invoice' movements MUST
    # point to their invoice line; sales and adjustments must NOT.
    op.create_check_constraint(
        "ck_movements_invoice_item_link",
        "stock_movements",
        "(reason = 'invoice') = (invoice_item_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_movements_invoice_item_link", "stock_movements", type_="check")
    op.drop_constraint("uq_stock_movements_invoice_item", "stock_movements", type_="unique")
    op.drop_column("stock_movements", "invoice_item_id")  # also drops its foreign key

    op.drop_constraint("uq_invoice_items_invoice_line", "invoice_items", type_="unique")
    op.drop_constraint("ck_invoice_items_line_no_positive", "invoice_items", type_="check")
    op.drop_column("invoice_items", "raw_sku")
    op.drop_column("invoice_items", "line_no")

    op.drop_constraint("ck_invoices_failed_has_error", "invoices", type_="check")
    op.drop_constraint("ck_invoices_processing_has_lease", "invoices", type_="check")
    op.drop_constraint("ck_invoices_attempts_non_negative", "invoices", type_="check")
    op.drop_column("invoices", "processing_started_at")
    op.drop_column("invoices", "attempts")