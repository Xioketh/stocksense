from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ErrorResponse, ProductCreate, ProductList, ProductOut
from app.security import require_api_key
from app.services import stock_service

router = APIRouter(
    prefix="/products",
    tags=["products"],
    dependencies=[Depends(require_api_key)],  # every endpoint here needs the API key
)


@router.post(
    "",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def create_product(data: ProductCreate, db: Session = Depends(get_db)):
    return stock_service.create_product(db, data)


@router.get("", response_model=ProductList)
def list_products(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    items, total = stock_service.list_products(db, limit=limit, offset=offset)
    return ProductList(
        items=[ProductOut.model_validate(p) for p in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{sku}", response_model=ProductOut, responses={404: {"model": ErrorResponse}})
def get_product(sku: str, db: Session = Depends(get_db)):
    return stock_service.get_product_by_sku(db, sku)