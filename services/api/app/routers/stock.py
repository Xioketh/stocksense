from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import ErrorResponse, StockOutRequest, StockOutResponse
from app.security import require_api_key
from app.services import stock_service

router = APIRouter(
    prefix="/stock",
    tags=["stock"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/out",
    response_model=StockOutResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def stock_out(data: StockOutRequest, db: Session = Depends(get_db)):
    """Record a sale: reduce stock for one product."""
    return stock_service.record_sale(db, sku=data.sku, qty=data.qty)
