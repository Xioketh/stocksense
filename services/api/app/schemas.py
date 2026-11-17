from datetime import datetime

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


class ErrorResponse(BaseModel):
    detail: str