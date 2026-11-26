"""Database operations for invoices. Routers call these functions."""

import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError
from app.models import Invoice, InvoiceItem, Product, StockMovement
from app.schemas import ResolveResponse, UploadUrlRequest, UploadUrlResponse
from app.storage import UploadSigner

logger = logging.getLogger(__name__)

FILE_EXTENSIONS = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


def new_object_name(content_type: str) -> str:
    """Build the object name on the SERVER, never from the client's filename.

    A random UUID means: no path tricks ("../../x"), no overwriting another
    invoice, and names that can't be guessed. The "invoices/" prefix lets the
    bucket notification watch only this folder.
    """
    return f"invoices/{uuid.uuid4().hex}.{FILE_EXTENSIONS[content_type]}"


def create_upload(db: Session, signer: UploadSigner, data: UploadUrlRequest) -> UploadUrlResponse:
    object_name = new_object_name(data.content_type)

    # Sign FIRST: if signing fails (e.g. missing IAM role), we don't leave
    # an invoice row behind that can never be uploaded.
    signed = signer.create_upload_url(object_name, data.content_type)

    invoice = Invoice(
        gcs_path=object_name,
        original_filename=data.filename,
        content_type=data.content_type,
        status="pending_upload",
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)

    logger.info("upload url created", extra={"invoice_id": invoice.id, "gcs_path": object_name})
    return UploadUrlResponse(
        invoice_id=invoice.id,
        upload_url=signed.url,
        headers=signed.headers,
        expires_at=signed.expires_at,
    )


def list_invoices(
    db: Session, limit: int, offset: int, status: str | None = None
) -> tuple[list[Invoice], int]:
    query = select(Invoice)
    count_query = select(func.count()).select_from(Invoice)
    if status is not None:
        query = query.where(Invoice.status == status)
        count_query = count_query.where(Invoice.status == status)

    total = db.scalar(count_query) or 0
    # Newest first: that's what the shop owner wants to see.
    items = db.scalars(query.order_by(Invoice.id.desc()).limit(limit).offset(offset)).all()
    return list(items), total


def get_invoice(db: Session, invoice_id: int) -> Invoice:
    # selectinload fetches the items in one extra query, instead of
    # one query per item later (the "N+1 queries" problem).
    invoice = db.scalar(
        select(Invoice).where(Invoice.id == invoice_id).options(selectinload(Invoice.items))
    )
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    return invoice

def list_review_items(db: Session, limit: int, offset: int) -> tuple[list[InvoiceItem], int]:
    """Lines the AI couldn't match, across ALL invoices: newest invoice first."""
    condition = InvoiceItem.status == "needs_review"
    total = db.scalar(select(func.count()).select_from(InvoiceItem).where(condition)) or 0
    items = db.scalars(
        select(InvoiceItem)
        .where(condition)
        .order_by(InvoiceItem.invoice_id.desc(), InvoiceItem.line_no)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), total


def resolve_review_item(db: Session, invoice_id: int, line_no: int, sku: str) -> ResolveResponse:
    """The owner says which product a needs_review line is. ONE transaction:
    mark the line matched, add its qty to stock, write the audit row. All or nothing.
    """
    log = {"invoice_id": invoice_id, "line_no": line_no, "sku": sku}

    # Lock THIS line until we commit. Two resolves of the same line (a double
    # click, or an agent retry) queue up here, and the second one sees
    # status='matched' below and gets 409 instead of adding stock again.
    item = db.scalar(
        select(InvoiceItem)
        .where(InvoiceItem.invoice_id == invoice_id, InvoiceItem.line_no == line_no)
        .with_for_update()
    )
    if item is None:
        raise NotFoundError(f"Invoice {invoice_id} has no line {line_no}")
    if item.status != "needs_review":
        db.rollback()  # release the row lock
        raise ConflictError(f"Invoice {invoice_id} line {line_no} is already {item.status}")

    # qty = qty + n is done BY THE DATABASE, like the worker does: safe even if a
    # sale changes the same product at the same moment. RETURNING gives us the
    # product id and the new qty in the same step; no row back = unknown SKU.
    row = db.execute(
        update(Product)
        .where(Product.sku == sku)
        .values(qty=Product.qty + item.qty)
        .returning(Product.id, Product.qty)
    ).one_or_none()
    if row is None:
        db.rollback()
        raise NotFoundError(f"Product with SKU '{sku}' not found")

    item.status = "matched"
    item.matched_product_id = row.id
    db.add(
        StockMovement(
            product_id=row.id,
            change=item.qty,
            reason="invoice",
            invoice_id=invoice_id,
            invoice_item_id=item.id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Last guard: UNIQUE(invoice_item_id) says this line already changed stock.
        db.rollback()
        raise ConflictError(f"Invoice {invoice_id} line {line_no} already changed stock")

    # No LowStock event: adding stock can never take a product INTO low stock.
    logger.info("review item resolved", extra={**log, "added": item.qty, "new_qty": row.qty})
    return ResolveResponse(
        invoice_id=invoice_id, line_no=line_no, sku=sku, added=item.qty, new_qty=row.qty
    )