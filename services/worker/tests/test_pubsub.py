"""Tests for POST /pubsub/invoice-uploaded (what Pub/Sub push calls)."""

from sqlalchemy.exc import OperationalError

from app.db import SessionLocal
from app.models import Invoice
from app.routers import pubsub
from tests.factories import make_envelope

URL = "/pubsub/invoice-uploaded"


def get_invoice(invoice_id: int) -> Invoice:
    with SessionLocal() as db:
        return db.get(Invoice, invoice_id)


def test_new_upload_marks_invoice_uploaded(client, pending_invoice):
    response = client.post(URL, json=make_envelope())

    assert response.status_code == 200  # 2xx = ack
    assert response.json() == {"outcome": "marked_uploaded"}
    invoice = get_invoice(pending_invoice.id)
    assert invoice.status == "uploaded"
    assert invoice.uploaded_at is not None


def test_duplicate_delivery_is_acked_and_changes_nothing(client, pending_invoice):
    # Pub/Sub delivers "at least once": the same message can arrive twice.
    client.post(URL, json=make_envelope())
    first_uploaded_at = get_invoice(pending_invoice.id).uploaded_at

    response = client.post(URL, json=make_envelope())

    assert response.status_code == 200
    assert response.json() == {"outcome": "duplicate"}
    assert get_invoice(pending_invoice.id).uploaded_at == first_uploaded_at


def test_unknown_object_is_acked(client):
    response = client.post(URL, json=make_envelope(object_id="invoices/nobody.pdf"))

    assert response.status_code == 200
    assert response.json() == {"outcome": "unknown_object"}


def test_event_from_another_bucket_is_ignored(client, pending_invoice):
    response = client.post(URL, json=make_envelope(bucket_id="someone-elses-bucket"))

    assert response.json() == {"outcome": "ignored"}
    assert get_invoice(pending_invoice.id).status == "pending_upload"


def test_other_event_types_are_ignored(client, pending_invoice):
    response = client.post(URL, json=make_envelope(event_type="OBJECT_DELETE"))

    assert response.json() == {"outcome": "ignored"}
    assert get_invoice(pending_invoice.id).status == "pending_upload"


def test_message_without_storage_attributes_is_acked(client):
    body = make_envelope()
    body["message"]["attributes"] = {}

    response = client.post(URL, json=body)

    assert response.status_code == 200
    assert response.json() == {"outcome": "ignored"}


def test_malformed_envelope_is_rejected(client):
    # Not a Pub/Sub envelope at all -> 422 (non-2xx), so Pub/Sub retries
    # it and, after max attempts, moves it to the dead-letter topic.
    response = client.post(URL, json={"hello": "world"})

    assert response.status_code == 422


def test_database_down_returns_503_so_pubsub_retries(client, monkeypatch):
    def broken(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(pubsub, "handle_storage_event", broken)

    response = client.post(URL, json=make_envelope())

    assert response.status_code == 503


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
