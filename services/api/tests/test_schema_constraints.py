"""The database's own safety nets (migration 0003).

The worker's code is the FIRST line of defence against processing an invoice
twice. These constraints are the LAST line: even if that code has a bug,
Postgres itself refuses the bad data.
"""

import pytest
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models import Invoice, InvoiceItem, StockMovement


def make_processed_invoice_with_rice_line(db, rice_id: int) -> InvoiceItem:
    invoice = Invoice(
        gcs_path="invoices/safety-net.pdf",
        original_filename="safety-net.pdf",
        content_type="application/pdf",
        status="processed",
    )
    item = InvoiceItem(
        line_no=1,
        raw_sku="RICE-5",
        raw_name="Rice 5kg",
        qty=20,
        matched_product_id=rice_id,
        status="matched",
    )
    invoice.items = [item]
    db.add(invoice)
    db.commit()
    return item


def test_same_invoice_line_cannot_change_stock_twice(rice):
    with SessionLocal() as db:
        item = make_processed_invoice_with_rice_line(db, rice["id"])

        def movement() -> StockMovement:
            return StockMovement(
                product_id=rice["id"],
                change=item.qty,
                reason="invoice",
                invoice_id=item.invoice_id,
                invoice_item_id=item.id,
            )

        db.add(movement())
        db.commit()  # the first time is fine

        db.add(movement())
        with pytest.raises(IntegrityError, match="uq_stock_movements_invoice_item"):
            db.commit()


def test_same_line_number_cannot_be_saved_twice(rice):
    with SessionLocal() as db:
        item = make_processed_invoice_with_rice_line(db, rice["id"])

        db.add(
            InvoiceItem(
                invoice_id=item.invoice_id,
                line_no=1,  # already used by the rice line
                raw_name="Rice 5kg (again)",
                qty=20,
                status="needs_review",
            )
        )
        with pytest.raises(IntegrityError, match="uq_invoice_items_invoice_line"):
            db.commit()


def test_failed_invoice_must_have_an_error_message():
    with SessionLocal() as db:
        db.add(
            Invoice(
                gcs_path="invoices/broken.pdf",
                original_filename="broken.pdf",
                content_type="application/pdf",
                status="failed",  # but no error_message
            )
        )
        with pytest.raises(IntegrityError, match="ck_invoices_failed_has_error"):
            db.commit()