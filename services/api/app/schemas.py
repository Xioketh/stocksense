from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    """Body for POST /products."""

    sku: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z0-9-]+$", examples=["RICE-5"])
    name: str = Field(min_length=1, max_length=200, examples=["Rice 5kg"])
    qty: int = Field(default=0, ge=0, examples=[20])
    low_stock_threshold: int = Field(default=0, ge=0, examples=[5])


class ProductOut(BaseModel):
    """What the API returns for a product."""

    model_config = ConfigDict(from_attributes=True)  # allow building from an ORM object

    id: int
    sku: str
    name: str
    qty: int
    low_stock_threshold: int
    is_low_stock: bool
    created_at: datetime


class ProductList(BaseModel):
    items: list[ProductOut]
    total: int
    limit: int
    offset: int


class StockOutRequest(BaseModel):
    """Body for POST /stock/out (record a sale)."""

    sku: str = Field(min_length=1, max_length=64, examples=["RICE-5"])
    qty: int = Field(gt=0, le=100_000, examples=[16])


class StockOutResponse(BaseModel):
    sku: str
    old_qty: int
    new_qty: int
    low_stock: bool


InvoiceStatus = Literal["pending_upload", "uploaded", "processing", "processed", "failed"]
InvoiceContentType = Literal["application/pdf", "image/jpeg", "image/png"]


class UploadUrlRequest(BaseModel):
    """Body for POST /invoices/upload-url."""

    filename: str = Field(min_length=1, max_length=255, examples=["supplier-invoice-0042.pdf"])
    content_type: InvoiceContentType = Field(examples=["application/pdf"])


class UploadUrlResponse(BaseModel):
    invoice_id: int
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]  # send these exact headers with the upload, or it fails
    expires_at: datetime


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    line_no: int
    raw_sku: str | None
    raw_name: str
    qty: int
    matched_product_id: int | None
    status: Literal["matched", "needs_review"]


class InvoiceOut(BaseModel):
    """An invoice in a list (without its items)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: InvoiceStatus
    original_filename: str
    content_type: str
    error_message: str | None
    attempts: int
    created_at: datetime
    uploaded_at: datetime | None
    processed_at: datetime | None


class InvoiceDetail(InvoiceOut):
    """One invoice with the items the AI found (empty until Phase 4)."""

    items: list[InvoiceItemOut]


class InvoiceList(BaseModel):
    items: list[InvoiceOut]
    total: int
    limit: int
    offset: int


class ErrorResponse(BaseModel):
    detail: str

class ReviewItemOut(BaseModel):
    """One invoice line the AI couldn't match, waiting for the owner to pick a product."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: int
    line_no: int
    raw_sku: str | None
    raw_name: str
    qty: int


class ReviewItemList(BaseModel):
    items: list[ReviewItemOut]
    total: int
    limit: int
    offset: int


class ResolveRequest(BaseModel):
    """Body for POST /invoices/{invoice_id}/items/{line_no}/resolve."""

    sku: str = Field(min_length=1, max_length=64, examples=["RICE-5"])


class ResolveResponse(BaseModel):
    invoice_id: int
    line_no: int
    sku: str
    added: int  # how much stock this line added
    new_qty: int  # the product's stock after adding it