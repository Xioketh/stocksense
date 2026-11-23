"""Tests for POST /pubsub/invoice-uploaded (what Pub/Sub push calls).

Gemini and the bucket are fakes (see conftest.py); the database is real.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app import extraction, storage
from app.db import SessionLocal
from app.extraction import ExtractionFailed, ExtractionUnavailable
from app.main import app
from app.models import Invoice, Product
from app.routers import pubsub
from tests.factories import insert_product, make_envelope

URL = "/pubsub/invoice-uploaded"


def get_invoice(invoice_id: int) -> Invoice:
    with SessionLocal() as db:
        return db.get(Invoice, invoice_id)


def stock(sku: str) -> int:
    with SessionLocal() as db:
        return db.query(Product).filter_by(sku=sku).one().qty


@pytest.fixture
def nimals_products():
    """The brief's user story: Rice 5kg has 4 left, Sugar 1kg has 30."""
    insert_product("RICE-5", qty=4)
    insert_product("SUGAR-1", qty=30)


# ---------- the full flow: upload event -> Gemini -> stock ----------


def test_new_upload_is_processed_and_stock_goes_up(client, pending_invoice, nimals_products):
    response = client.post(URL, json=make_envelope())

    assert response.status_code == 200  # 2xx = ack
    assert response.json() == {"outcome": "marked_uploaded", "processing": "processed"}
    assert stock("RICE-5") == 24  # 4 + 20 (the fake answers with Nimal's invoice)
    assert stock("SUGAR-1") == 55  # 30 + 25
    invoice = get_invoice(pending_invoice.id)
    assert invoice.status == "processed"
    assert invoice.uploaded_at is not None


def test_duplicate_delivery_is_acked_and_adds_nothing(
    client, pending_invoice, nimals_products, fake_extractor
):
    # Pub/Sub delivers "at least once": the same message can arrive twice.
    client.post(URL, json=make_envelope())

    response = client.post(URL, json=make_envelope())

    assert response.status_code == 200
    assert response.json() == {"outcome": "duplicate", "processing": "already_done"}
    assert stock("RICE-5") == 24  # not 44
    assert len(fake_extractor.calls) == 1


def test_temporary_problem_returns_503_so_pubsub_retries(
    client, pending_invoice, nimals_products, fake_extractor
):
    fake_extractor.error = ExtractionUnavailable("Gemini error 429 RESOURCE_EXHAUSTED")

    response = client.post(URL, json=make_envelope())

    assert response.status_code == 503
    assert response.json()["processing"] == "retry_later"
    assert get_invoice(pending_invoice.id).status == "uploaded"  # ready for the next try

    # Next delivery: Gemini answers this time.
    fake_extractor.error = None
    retry = client.post(URL, json=make_envelope(delivery_attempt=2))

    assert retry.status_code == 200
    assert retry.json() == {"outcome": "duplicate", "processing": "processed"}
    assert stock("RICE-5") == 24


def test_last_delivery_attempt_gives_up_and_acks(client, pending_invoice, fake_extractor):
    fake_extractor.error = ExtractionUnavailable("Gemini error 503 UNAVAILABLE")

    response = client.post(URL, json=make_envelope(delivery_attempt=5))  # max_delivery_attempts

    assert response.status_code == 200  # ack: Pub/Sub would not deliver it again anyway
    assert response.json()["processing"] == "failed"
    assert get_invoice(pending_invoice.id).error_message.startswith("Gave up")


def test_permanent_problem_is_acked_with_reason(client, pending_invoice, fake_extractor):
    fake_extractor.error = ExtractionFailed("The file does not look like a supplier invoice")

    response = client.post(URL, json=make_envelope())

    assert response.status_code == 200  # retrying the same file can't help
    assert response.json()["processing"] == "failed"
    invoice = get_invoice(pending_invoice.id)
    assert invoice.status == "failed"
    assert invoice.error_message == "The file does not look like a supplier invoice"


# ---------- messages with nothing to process (unchanged from Phase 3) ----------


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


# ---------- startup check ----------


def test_misconfigured_worker_refuses_to_start(monkeypatch):
    # On Cloud Run (APP_ENV=prod) with the default fake backends: must NOT start.
    monkeypatch.setenv("APP_ENV", "prod")
    caches = [extraction.get_settings, extraction.get_extractor, storage.get_invoice_files]
    for cached in caches:
        cached.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="not allowed"):
            with TestClient(app):  # "with" runs the startup (lifespan) code
                pass
    finally:
        monkeypatch.undo()
        for cached in caches:
            cached.cache_clear()