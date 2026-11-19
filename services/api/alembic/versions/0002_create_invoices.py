"""create invoices and invoice_items; link stock_movements to invoices

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19

Additive only ("expand"): new tables and a new NULLABLE column.
The old app version keeps working while this runs, so it is safe to
migrate first and deploy the new code afterwards (as deploy.yml does).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("gcs_path", sa.String(length=300), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending_upload', 'uploaded', 'processing', 'processed', 'failed')",
            name="ck_invoices_status",
        ),
    )
    op.create_index("ix_invoices_gcs_path", "invoices", ["gcs_path"], unique=True)
    op.create_index("ix_invoices_status", "invoices", ["status"])

    op.create_table(
        "invoice_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("raw_name", sa.String(length=200), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("matched_product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("qty > 0", name="ck_invoice_items_qty_positive"),
        sa.CheckConstraint("status IN ('matched', 'needs_review')", name="ck_invoice_items_status"),
        sa.CheckConstraint(
            "(status = 'matched') = (matched_product_id IS NOT NULL)",
            name="ck_invoice_items_match_link",
        ),
    )
    op.create_index("ix_invoice_items_invoice_id", "invoice_items", ["invoice_id"])

    # Existing rows are all sales, so invoice_id = NULL satisfies the new CHECK.
    op.add_column(
        "stock_movements",
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
    )
    op.create_index("ix_stock_movements_invoice_id", "stock_movements", ["invoice_id"])
    op.create_check_constraint(
        "ck_movements_invoice_link",
        "stock_movements",
        "(reason = 'invoice') = (invoice_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_movements_invoice_link", "stock_movements", type_="check")
    op.drop_index("ix_stock_movements_invoice_id", table_name="stock_movements")
    op.drop_column("stock_movements", "invoice_id")  # also drops its foreign key
    op.drop_index("ix_invoice_items_invoice_id", table_name="invoice_items")
    op.drop_table("invoice_items")
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_gcs_path", table_name="invoices")
    op.drop_table("invoices")
