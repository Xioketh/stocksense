"""Tests for the processing pipeline, on the REAL schema (API migrations).

Gemini and Cloud Storage are fakes; the database is real, because the
claim, the fencing and the constraints ARE database behaviour.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import text

from app.db import SessionLocal, engine
from app.extraction import (
    ExtractedLine,
    ExtractionFailed,
    ExtractionUnavailable,
    InvoiceExtraction,
)
from app.extraction.fake import FakeExtractor
from app.services.invoice_processing import Result, process_invoice
from app.storage import FakeInvoiceFiles
from tests.factories import insert_invoice, insert_product

PATH = "invoices/nimal-0142.pdf"
LEASE_SECONDS = 600


def extraction(*lines: tuple[str | None, int]) -> InvoiceExtraction:
    return InvoiceExtraction(
        lines=[ExtractedLine(sku=sku, name=sku or "No code", qty=qty) for sku, qty in lines]
    )


NIMAL = extraction(("RICE-5", 20), ("SUGAR-1", 25), ("COCO-750", 10))


def run(invoice_id, extractor=None, files=None, final_delivery=False) -> Result:
    with SessionLocal() as db:
        return process_invoice(
            db,
            invoice_id,
            files=files or FakeInvoiceFiles({PATH: b"%PDF-1.7 invoice"}),
            extractor=extractor or FakeExtractor(NIMAL),
            lease_seconds=LEASE_SECONDS,
            final_delivery=final_delivery,
        )


# ---------- small helpers to look at the database ----------


def query(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def stock(sku: str) -> int:
    return query("SELECT qty FROM products WHERE sku = :sku", sku=sku)[0].qty


def invoice(invoice_id: int):
    return query("SELECT * FROM invoices WHERE id = :id", id=invoice_id)[0]


def movement_count(invoice_id: int) -> int:
    return len(query("SELECT id FROM stock_movements WHERE invoice_id = :id", id=invoice_id))


def start_processing(invoice_id: int, seconds_ago: int) -> None:
    """Pretend another worker claimed this invoice `seconds_ago` seconds ago."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE invoices SET status = 'processing', attempts = 1, "
                "processing_started_at = now() - make_interval(secs => :s) WHERE id = :id"
            ),
            {"s": seconds_ago, "id": invoice_id},
        )


def nimals_shop() -> int:
    """The brief's user story: Rice 4 (low), Sugar 30, and an uploaded invoice."""
    insert_product("RICE-5", qty=4)
    insert_product("SUGAR-1", qty=30)
    return insert_invoice(gcs_path=PATH, status="uploaded")


# ---------- the happy path ----------


def test_invoice_adds_stock_and_flags_unknown_items():
    invoice_id = nimals_shop()

    assert run(invoice_id) == Result.PROCESSED

    assert stock("RICE-5") == 24  # 4 + 20
    assert stock("SUGAR-1") == 55  # 30 + 25
    items = query(
        "SELECT line_no, raw_sku, status FROM invoice_items "
        "WHERE invoice_id = :id ORDER BY line_no",
        id=invoice_id,
    )
    assert [tuple(row) for row in items] == [
        (1, "RICE-5", "matched"),
        (2, "SUGAR-1", "matched"),
        (3, "COCO-750", "needs_review"),  # Coconut oil: not in the catalog
    ]
    assert movement_count(invoice_id) == 2  # one per MATCHED line
    row = invoice(invoice_id)
    assert (row.status, row.attempts) == ("processed", 1)
    assert row.processed_at is not None


def test_same_product_on_two_lines_adds_both():
    insert_product("RICE-5", qty=0)
    invoice_id = insert_invoice(gcs_path=PATH, status="uploaded")

    run(invoice_id, extractor=FakeExtractor(extraction(("RICE-5", 20), ("RICE-5", 5))))

    assert stock("RICE-5") == 25
    assert movement_count(invoice_id) == 2


# ---------- idempotency ----------


def test_duplicate_delivery_does_not_add_stock_twice():
    invoice_id = nimals_shop()
    extractor = FakeExtractor(NIMAL)

    first = run(invoice_id, extractor=extractor)
    second = run(invoice_id, extractor=extractor)  # Pub/Sub delivered it again

    assert (first, second) == (Result.PROCESSED, Result.ALREADY_DONE)
    assert stock("RICE-5") == 24  # NOT 44
    assert len(extractor.calls) == 1  # Gemini was not even asked again


def test_two_deliveries_at_the_same_moment_add_stock_once():
    invoice_id = nimals_shop()
    start_line = Barrier(2)  # both "workers" start at exactly the same time

    def worker() -> Result:
        start_line.wait()
        return run(invoice_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(lambda _: worker(), range(2)))

    # One wins the claim. The other finds it busy (503, retry) or already done (ack).
    assert results.count(Result.PROCESSED) == 1
    assert stock("RICE-5") == 24
    assert movement_count(invoice_id) == 2


def test_invoice_another_worker_is_processing_is_left_alone():
    invoice_id = nimals_shop()
    start_processing(invoice_id, seconds_ago=10)  # a fresh lease
    extractor = FakeExtractor(NIMAL)

    assert run(invoice_id, extractor=extractor) == Result.IN_PROGRESS
    assert extractor.calls == []
    assert stock("RICE-5") == 4


def test_stale_lease_is_taken_over():
    invoice_id = nimals_shop()
    start_processing(invoice_id, seconds_ago=LEASE_SECONDS + 60)  # that worker died

    assert run(invoice_id) == Result.PROCESSED
    assert invoice(invoice_id).attempts == 2
    assert stock("RICE-5") == 24


class TakenOverWhileReading(FakeExtractor):
    """While 'Gemini' is working, another worker takes the invoice over."""

    def extract(self, content, mime_type):
        with engine.begin() as conn:  # a separate connection = the other worker
            conn.execute(
                text(
                    "UPDATE invoices SET attempts = attempts + 1, "
                    "processing_started_at = now() WHERE gcs_path = :p"
                ),
                {"p": PATH},
            )
        return super().extract(content, mime_type)


def test_worker_that_lost_its_lease_writes_nothing():
    invoice_id = nimals_shop()

    assert run(invoice_id, extractor=TakenOverWhileReading(NIMAL)) == Result.LOST_LEASE

    assert stock("RICE-5") == 4  # unchanged: the new owner will add the stock
    assert query("SELECT id FROM invoice_items WHERE invoice_id = :id", id=invoice_id) == []
    assert invoice(invoice_id).status == "processing"  # still the new owner's


# ---------- failures ----------


def test_permanent_problem_marks_invoice_failed_with_reason():
    invoice_id = nimals_shop()
    not_invoice = FakeExtractor(error=ExtractionFailed("The file does not look like an invoice"))

    assert run(invoice_id, extractor=not_invoice) == Result.FAILED

    row = invoice(invoice_id)
    assert row.status == "failed"
    assert row.error_message == "The file does not look like an invoice"
    assert stock("RICE-5") == 4


def test_missing_file_fails_without_asking_gemini():
    invoice_id = nimals_shop()
    extractor = FakeExtractor(NIMAL)

    result = run(invoice_id, extractor=extractor, files=FakeInvoiceFiles())  # empty bucket

    assert result == Result.FAILED
    assert "not in the bucket" in invoice(invoice_id).error_message
    assert extractor.calls == []


def test_temporary_problem_releases_invoice_for_the_next_delivery():
    invoice_id = nimals_shop()
    busy = FakeExtractor(error=ExtractionUnavailable("Gemini error 429 RESOURCE_EXHAUSTED"))

    assert run(invoice_id, extractor=busy) == Result.RETRY_LATER
    row = invoice(invoice_id)
    assert (row.status, row.attempts, row.processing_started_at) == ("uploaded", 1, None)

    # Pub/Sub delivers again later, and this time Gemini answers.
    assert run(invoice_id) == Result.PROCESSED
    assert invoice(invoice_id).attempts == 2
    assert stock("RICE-5") == 24


def test_last_delivery_gives_up_instead_of_waiting_forever():
    invoice_id = nimals_shop()
    busy = FakeExtractor(error=ExtractionUnavailable("Gemini error 503 UNAVAILABLE"))

    assert run(invoice_id, extractor=busy, final_delivery=True) == Result.FAILED
    assert invoice(invoice_id).error_message.startswith("Gave up after repeated temporary errors")