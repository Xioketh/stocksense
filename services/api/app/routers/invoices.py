from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    ErrorResponse,
    InvoiceDetail,
    InvoiceList,
    InvoiceOut,
    InvoiceStatus,
    ResolveRequest,
    ResolveResponse,
    ReviewItemList,
    ReviewItemOut,
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

# Declared BEFORE "/{invoice_id}" on purpose. FastAPI tries routes in order, so
# if "/{invoice_id}" came first it would grab "/review-items" and fail with 422
# ("review-items" is not an int).
@router.get("/review-items", response_model=ReviewItemList)
def list_review_items(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Invoice lines the AI couldn't match (status needs_review), across all invoices."""
    items, total = invoice_service.list_review_items(db, limit=limit, offset=offset)
    return ReviewItemList(
        items=[ReviewItemOut.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{invoice_id}/items/{line_no}/resolve",
    response_model=ResolveResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def resolve_review_item(
    invoice_id: int, line_no: int, data: ResolveRequest, db: Session = Depends(get_db)
):
    """Match a needs_review line to a product and add its qty to stock (once).

    404: the line or the SKU doesn't exist. 409: the line is already matched.
    """
    return invoice_service.resolve_review_item(db, invoice_id, line_no, data.sku)

@router.get(
    "/{invoice_id}",
    response_model=InvoiceDetail,
    responses={404: {"model": ErrorResponse}},
)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return invoice_service.get_invoice(db, invoice_id)
