from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    ErrorResponse,
    InvoiceDetail,
    InvoiceList,
    InvoiceOut,
    InvoiceStatus,
    UploadUrlRequest,
    UploadUrlResponse,
)
from app.security import require_api_key
from app.services import invoice_service
from app.storage import UploadSigner, get_upload_signer

router = APIRouter(
    prefix="/invoices",
    tags=["invoices"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/upload-url",
    response_model=UploadUrlResponse,
    status_code=status.HTTP_201_CREATED,  # 201: this also creates an invoice record
)
def create_upload_url(
    data: UploadUrlRequest,
    db: Session = Depends(get_db),
    signer: UploadSigner = Depends(get_upload_signer),
):
    """Get a short-lived URL to upload one invoice file DIRECTLY to Cloud Storage.

    Then: PUT the file to upload_url, sending the returned headers.
    """
    return invoice_service.create_upload(db, signer, data)


@router.get("", response_model=InvoiceList)
def list_invoices(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: InvoiceStatus | None = Query(default=None),
    db: Session = Depends(get_db),
):
    items, total = invoice_service.list_invoices(db, limit=limit, offset=offset, status=status)
    return InvoiceList(
        items=[InvoiceOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetail,
    responses={404: {"model": ErrorResponse}},
)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return invoice_service.get_invoice(db, invoice_id)
