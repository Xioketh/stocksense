"""API tests for needs_review lines: listing them and resolving them to a product.

The worker isn't running in these tests, so each test saves a processed
invoice with its lines directly in the database (what the worker would do).
"""

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Invoice, InvoiceItem, Product, StockMovement


def save_invoice(gcs_name: str, items: list[InvoiceItem]) -> int:
    """Save a processed invoice with these lines and return its id."""
    with SessionLocal() as db:
        invoice = Invoice(
            gcs_path=f"invoices/{gcs_name}.pdf",
            original_filename=f"{gcs_name}.pdf",
            content_type="application/pdf",
            status="processed",
        )
        invoice.items = items
        db.add(invoice)
        db.commit()
        return invoice.id


@pytest.fixture
def invoice_id(rice) -> int:
    """Invoice with 1 matched line (rice) and 1 needs_review line (12 bags of rice)."""
    return save_invoice(
        "inv-a",
        [
            InvoiceItem(
                line_no=1,
                raw_sku="RICE-5",
                raw_name="Rice 5kg",
                qty=20,
                matched_product_id=rice["id"],
                status="matched",
            ),
            InvoiceItem(
                line_no=2, raw_sku=None, raw_name="Basmathi Rice 5kg", qty=12, status="needs_review"
            ),
        ],
    )


def resolve(client, invoice_id: int, line_no: int, sku: str):
    return client.post(f"/invoices/{invoice_id}/items/{line_no}/resolve", json={"sku": sku})


# ---------- GET /invoices/review-items ----------


def test_review_items_lists_only_needs_review_lines_newest_invoice_first(client, invoice_id):
    newer_id = save_invoice(
        "inv-b",
        [
            InvoiceItem(
                line_no=1, raw_sku="COCO-750", raw_name="Coconut oil", qty=3, status="needs_review"
            )
        ],
    )

    response = client.get("/invoices/review-items")

    # 200, not 422: proves the route is declared before /{invoice_id}.
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["items"] == [
        {
            "invoice_id": newer_id,
            "line_no": 1,
            "raw_sku": "COCO-750",
            "raw_name": "Coconut oil",
            "qty": 3,
        },
        {
            "invoice_id": invoice_id,
            "line_no": 2,
            "raw_sku": None,
            "raw_name": "Basmathi Rice 5kg",
            "qty": 12,
        },
    ]


def test_review_items_empty_when_nothing_to_review(client):
    body = client.get("/invoices/review-items").json()

    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


# ---------- POST /invoices/{id}/items/{line_no}/resolve ----------


def test_resolve_adds_stock_and_marks_line_matched(client, rice, invoice_id):
    response = resolve(client, invoice_id, 2, "RICE-5")

    assert response.status_code == 200
    assert response.json() == {
        "invoice_id": invoice_id,
        "line_no": 2,
        "sku": "RICE-5",
        "added": 12,
        "new_qty": 32,  # 20 + 12
    }
    assert client.get("/products/RICE-5").json()["qty"] == 32
    line = client.get(f"/invoices/{invoice_id}").json()["items"][1]
    assert (line["status"], line["matched_product_id"]) == ("matched", rice["id"])
    assert client.get("/invoices/review-items").json()["total"] == 0


def test_resolve_writes_one_invoice_stock_movement(client, rice, invoice_id):
    resolve(client, invoice_id, 2, "RICE-5")

    with SessionLocal() as db:
        movements = db.scalars(select(StockMovement)).all()
    assert len(movements) == 1
    m = movements[0]
    assert (m.product_id, m.change, m.reason, m.invoice_id) == (
        rice["id"],
        12,
        "invoice",
        invoice_id,
    )
    assert m.invoice_item_id is not None


def test_second_resolve_returns_409_and_adds_stock_only_once(client, invoice_id):
    first = resolve(client, invoice_id, 2, "RICE-5")
    second = resolve(client, invoice_id, 2, "RICE-5")

    assert first.status_code == 200
    assert second.status_code == 409
    assert "already matched" in second.json()["detail"]
    assert client.get("/products/RICE-5").json()["qty"] == 32  # not 44


def test_resolve_line_the_worker_already_matched_returns_409(client, invoice_id):
    response = resolve(client, invoice_id, 1, "RICE-5")

    assert response.status_code == 409
    assert client.get("/products/RICE-5").json()["qty"] == 20


def test_resolve_unknown_line_returns_404(client, invoice_id):
    assert resolve(client, invoice_id, 99, "RICE-5").status_code == 404
    assert resolve(client, 999, 1, "RICE-5").status_code == 404


def test_resolve_unknown_sku_returns_404_and_changes_nothing(client, invoice_id):
    response = resolve(client, invoice_id, 2, "NOPE-1")

    assert response.status_code == 404
    assert "NOPE-1" in response.json()["detail"]
    with SessionLocal() as db:
        line = db.scalar(select(InvoiceItem).where(InvoiceItem.line_no == 2))
        rice_qty = db.scalar(select(Product.qty).where(Product.sku == "RICE-5"))
    assert (line.status, line.matched_product_id) == ("needs_review", None)
    assert rice_qty == 20


def test_resolve_with_empty_sku_returns_422(client, invoice_id):
    assert resolve(client, invoice_id, 2, "").status_code == 422


def test_review_endpoints_need_api_key(anon_client, invoice_id):
    assert anon_client.get("/invoices/review-items").status_code == 401
    response = anon_client.post(f"/invoices/{invoice_id}/items/2/resolve", json={"sku": "RICE-5"})
    assert response.status_code == 401