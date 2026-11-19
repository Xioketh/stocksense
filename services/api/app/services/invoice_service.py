"""Database operations for invoices. Routers call these functions."""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError
from app.models import Invoice
from app.schemas import UploadUrlRequest, UploadUrlResponse
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