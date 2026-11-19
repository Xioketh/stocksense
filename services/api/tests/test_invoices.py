"""API tests for /invoices. Cloud Storage is replaced by the FakeUploadSigner."""

from app.db import SessionLocal
from app.models import Invoice, InvoiceItem

PDF_REQUEST = {"filename": "supplier-invoice-0042.pdf", "content_type": "application/pdf"}


def test_upload_url_returns_201_and_signed_headers(client):
    response = client.post("/invoices/upload-url", json=PDF_REQUEST)

    assert response.status_code == 201
    body = response.json()
    assert body["invoice_id"] == 1
    assert body["method"] == "PUT"
    assert body["upload_url"].startswith("https://fake-gcs.invalid/test-invoices/invoices/")
    assert body["headers"]["Content-Type"] == "application/pdf"
    assert body["headers"]["X-Goog-Content-Length-Range"] == "0,10485760"


def test_upload_url_creates_pending_invoice(client):
    invoice_id = client.post("/invoices/upload-url", json=PDF_REQUEST).json()["invoice_id"]

    response = client.get(f"/invoices/{invoice_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending_upload"
    assert body["original_filename"] == "supplier-invoice-0042.pdf"
    assert body["items"] == []


def test_object_name_ignores_client_filename(client):
    # A malicious filename must NOT end up in the bucket path.
    client.post(
        "/invoices/upload-url",
        json={"filename": "../../other-shop/x.pdf", "content_type": "application/pdf"},
    )

    with SessionLocal() as db:
        invoice = db.get(Invoice, 1)
    assert invoice.gcs_path.startswith("invoices/")
    assert invoice.gcs_path.endswith(".pdf")
    assert ".." not in invoice.gcs_path
    assert "other-shop" not in invoice.gcs_path


def test_unsupported_content_type_returns_422(client):
    response = client.post(
        "/invoices/upload-url",
        json={"filename": "virus.exe", "content_type": "application/x-msdownload"},
    )

    assert response.status_code == 422


def test_list_invoices_newest_first_with_status_filter(client):
    for name in ["a.pdf", "b.pdf"]:
        client.post("/invoices/upload-url", json={**PDF_REQUEST, "filename": name})

    all_invoices = client.get("/invoices").json()
    uploaded_only = client.get("/invoices", params={"status": "uploaded"}).json()

    assert all_invoices["total"] == 2
    assert [i["original_filename"] for i in all_invoices["items"]] == ["b.pdf", "a.pdf"]
    assert uploaded_only["total"] == 0


def test_invoice_detail_includes_items(client, rice):
    # Simulate what the worker will do in Phase 4: save the extracted items.
    with SessionLocal() as db:
        invoice = Invoice(
            gcs_path="invoices/test.pdf",
            original_filename="test.pdf",
            content_type="application/pdf",
            status="processed",
        )
        invoice.items = [
            InvoiceItem(
                raw_name="Rice 5kg", qty=20, matched_product_id=rice["id"], status="matched"
            ),
            InvoiceItem(raw_name="Coconut oil", qty=10, status="needs_review"),
        ]
        db.add(invoice)
        db.commit()
        invoice_id = invoice.id

    body = client.get(f"/invoices/{invoice_id}").json()

    assert [(i["raw_name"], i["status"]) for i in body["items"]] == [
        ("Rice 5kg", "matched"),
        ("Coconut oil", "needs_review"),
    ]


def test_get_unknown_invoice_returns_404(client):
    response = client.get("/invoices/999")

    assert response.status_code == 404


def test_invoices_need_api_key(anon_client):
    response = anon_client.post("/invoices/upload-url", json=PDF_REQUEST)

    assert response.status_code == 401
