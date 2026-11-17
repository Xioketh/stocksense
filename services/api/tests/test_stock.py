"""API tests for POST /stock/out, following Nimal's user story."""

from sqlalchemy import select

from app.db import SessionLocal
from app.models import StockMovement


def test_sale_reduces_stock_and_flags_low_stock(client, rice):
    # Rice: 20 in stock, alert below 5. Sell 16 -> 4 left -> low stock.
    response = client.post("/stock/out", json={"sku": "RICE-5", "qty": 16})

    assert response.status_code == 200
    assert response.json() == {"sku": "RICE-5", "old_qty": 20, "new_qty": 4, "low_stock": True}

    # The product itself is updated too
    product = client.get("/products/RICE-5").json()
    assert product["qty"] == 4
    assert product["is_low_stock"] is True


def test_sale_records_a_stock_movement(client, rice):
    client.post("/stock/out", json={"sku": "RICE-5", "qty": 2})

    # Check the audit trail directly in the database
    with SessionLocal() as db:
        movements = db.scalars(select(StockMovement)).all()
    assert len(movements) == 1
    assert movements[0].change == -2
    assert movements[0].reason == "sale"


def test_selling_more_than_stock_returns_409_and_changes_nothing(client, rice):
    response = client.post("/stock/out", json={"sku": "RICE-5", "qty": 21})

    assert response.status_code == 409
    assert client.get("/products/RICE-5").json()["qty"] == 20


def test_sale_of_unknown_product_returns_404(client):
    response = client.post("/stock/out", json={"sku": "NOPE-1", "qty": 1})

    assert response.status_code == 404


def test_sale_with_zero_qty_returns_422(client, rice):
    response = client.post("/stock/out", json={"sku": "RICE-5", "qty": 0})

    assert response.status_code == 422