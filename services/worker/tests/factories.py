"""Helpers that build test data. (Kept out of conftest.py on purpose:
conftest is for fixtures, and importing from it is a known pytest gotcha.)"""

from sqlalchemy import text

from app.db import engine


def insert_invoice(
    gcs_path: str = "invoices/abc123.pdf",
    status: str = "pending_upload",
    original_filename: str = "supplier-invoice.pdf",
    content_type: str = "application/pdf",
) -> int:
    """Insert an invoice row the way the API does (POST /invoices/upload-url).

    Raw SQL on purpose: the worker's Invoice model maps only the columns
    the worker uses, but the real table also has NOT NULL columns the
    worker never touches (original_filename, content_type).
    """
    with engine.begin() as conn:
        return conn.scalar(
            text(
                "INSERT INTO invoices (gcs_path, original_filename, content_type, status) "
                "VALUES (:gcs_path, :original_filename, :content_type, :status) "
                "RETURNING id"
            ),
            {
                "gcs_path": gcs_path,
                "original_filename": original_filename,
                "content_type": content_type,
                "status": status,
            },
        )


def insert_product(sku: str, qty: int, name: str | None = None) -> int:
    """Insert a product the way POST /products does."""
    with engine.begin() as conn:
        return conn.scalar(
            text(
                "INSERT INTO products (sku, name, qty, low_stock_threshold) "
                "VALUES (:sku, :name, :qty, 5) RETURNING id"
            ),
            {"sku": sku, "name": name or sku, "qty": qty},
        )


def make_envelope(
    object_id: str = "invoices/abc123.pdf",
    event_type: str = "OBJECT_FINALIZE",
    bucket_id: str = "test-invoices",
    message_id: str = "1001",
    delivery_attempt: int = 1,
) -> dict:
    """Build a request body exactly like a Pub/Sub push delivery."""
    return {
        "message": {
            "attributes": {
                "eventType": event_type,
                "bucketId": bucket_id,
                "objectId": object_id,
                "objectGeneration": "1732071605123456",
                "payloadFormat": "JSON_API_V1",
            },
            "data": "e30=",  # base64 of "{}" (the worker doesn't read it yet)
            "messageId": message_id,
            "publishTime": "2026-11-20T10:25:36.123Z",
        },
        "subscription": "projects/test/subscriptions/invoice-uploaded-worker",
        "deliveryAttempt": delivery_attempt,
    }
