"""Process one uploaded invoice: claim it, read it with Gemini, update stock.

Pub/Sub may deliver the same message more than once, even at the same
moment. Stock must still increase exactly once. Three layers make sure:

1. CLAIM:    one atomic UPDATE moves the invoice 'uploaded' -> 'processing'.
             Only one delivery can win it.
2. FENCING:  winning the claim gives an attempt number (our "ticket"). The
             final save only works if the invoice is STILL processing under
             our ticket. If our lease expired and another worker took over,
             everything we were about to write is rolled back.
3. DATABASE: UNIQUE constraints (migration 0003) refuse a second copy of any
             invoice line or stock movement, even if 1 and 2 had a bug.

The slow steps (download + Gemini) run between two short transactions, so no
database connection is held while waiting for Gemini.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app.extraction import (
    ExtractionFailed,
    ExtractionUnavailable,
    InvoiceExtraction,
    InvoiceExtractor,
)
from app.models import Invoice, InvoiceItem, Product, StockMovement
from app.services.matching import match_lines
from app.storage import InvoiceFileError, InvoiceFiles, StorageUnavailable

logger = logging.getLogger(__name__)

ERROR_MESSAGE_MAX = 500  # invoices.error_message is VARCHAR(500)


class Result(StrEnum):
    """What happened. The push handler turns this into 200 (ack) or 503 (retry)."""

    PROCESSED = "processed"  # ack: stock updated
    FAILED = "failed"  # ack: permanent problem, reason saved on the invoice
    ALREADY_DONE = "already_done"  # ack: finished before (a duplicate delivery)
    LOST_LEASE = "lost_lease"  # ack: another worker took over and will finish it
    IN_PROGRESS = "in_progress"  # 503: another worker is on it right now; check later
    RETRY_LATER = "retry_later"  # 503: temporary problem, invoice released for a retry


@dataclass(frozen=True)
class Claim:
    invoice_id: int
    gcs_path: str
    content_type: str
    attempt: int  # the fencing ticket: invoices.attempts at the moment we claimed it


def process_invoice(
    db: Session,
    invoice_id: int,
    files: InvoiceFiles,
    extractor: InvoiceExtractor,
    lease_seconds: int,
    final_delivery: bool = False,
) -> Result:
    """Run the whole pipeline for one invoice.

    final_delivery=True means Pub/Sub will not deliver this message again
    (last attempt before the dead-letter topic): then a temporary problem
    marks the invoice 'failed' instead of leaving it waiting forever.
    """
    claim = _claim(db, invoice_id, lease_seconds)
    if claim is None:
        status = db.scalar(select(Invoice.status).where(Invoice.id == invoice_id))
        logger.info("invoice not claimed", extra={"invoice_id": invoice_id, "status": status})
        return Result.IN_PROGRESS if status == "processing" else Result.ALREADY_DONE

    log = {"invoice_id": claim.invoice_id, "attempt": claim.attempt}
    logger.info("invoice claimed", extra=log)

    # ---- the slow part: no transaction open here ----
    try:
        content = files.read(claim.gcs_path)
        extraction = extractor.extract(content, claim.content_type)
    except (InvoiceFileError, ExtractionFailed) as exc:
        return _mark_failed(db, claim, str(exc))
    except (StorageUnavailable, ExtractionUnavailable) as exc:
        if final_delivery:
            return _mark_failed(db, claim, f"Gave up after repeated temporary errors: {exc}")
        _release(db, claim)
        logger.warning("temporary problem, will retry", extra={**log, "error": str(exc)})
        return Result.RETRY_LATER

    return _save(db, claim, extraction)


# ---------------------------------------------------------------- steps


def _claim(db: Session, invoice_id: int, lease_seconds: int) -> Claim | None:
    """Atomically take the invoice, or return None if we may not.

    We may take it when it is 'uploaded' (normal case), or when it is
    'processing' but the lease is older than lease_seconds (the worker that
    had it was stopped). The database checks and changes the row in ONE
    statement, so two deliveries can never both win.
    """
    stale_before = func.now() - timedelta(seconds=lease_seconds)
    row = db.execute(
        update(Invoice)
        .where(
            Invoice.id == invoice_id,
            or_(
                Invoice.status == "uploaded",
                and_(Invoice.status == "processing", Invoice.processing_started_at < stale_before),
            ),
        )
        .values(
            status="processing",
            processing_started_at=func.now(),
            attempts=Invoice.attempts + 1,
            error_message=None,
        )
        .returning(Invoice.id, Invoice.gcs_path, Invoice.content_type, Invoice.attempts)
    ).one_or_none()
    db.commit()
    if row is None:
        return None
    return Claim(
        invoice_id=row.id,
        gcs_path=row.gcs_path,
        content_type=row.content_type,
        attempt=row.attempts,
    )


def _still_ours(claim: Claim):
    """SQL condition: the invoice is processing under OUR ticket (fencing)."""
    return and_(
        Invoice.id == claim.invoice_id,
        Invoice.status == "processing",
        Invoice.attempts == claim.attempt,
    )


def _save(db: Session, claim: Claim, extraction: InvoiceExtraction) -> Result:
    """ONE transaction: finish the invoice, save its lines, add stock. All or nothing."""
    log = {"invoice_id": claim.invoice_id, "attempt": claim.attempt}

    # Fencing FIRST. This UPDATE also locks the invoice row until we commit,
    # so nobody can take the invoice over while we write.
    finished = db.execute(
        update(Invoice)
        .where(_still_ours(claim))
        .values(status="processed", processed_at=func.now(), error_message=None)
    ).rowcount
    if finished == 0:
        db.rollback()
        logger.warning("lease lost before saving, nothing written", extra=log)
        return Result.LOST_LEASE

    skus = {line.sku for line in extraction.lines if line.sku}
    rows = db.execute(select(Product.sku, Product.id).where(Product.sku.in_(skus))).all()
    product_ids = {sku: product_id for sku, product_id in rows}
    matched = match_lines(extraction.lines, product_ids)

    items = [
        InvoiceItem(
            invoice_id=claim.invoice_id,
            line_no=line.line_no,
            raw_sku=line.sku,
            raw_name=line.name,
            qty=line.qty,
            matched_product_id=line.product_id,
            status=line.status,
        )
        for line in matched
    ]
    db.add_all(items)
    db.flush()  # sends the INSERTs now, so each item has its id for the movements

    # Stock: always in the same order (product id), so two workers updating
    # the same products can never wait for each other in a circle (deadlock).
    stock_items = sorted(
        (item for item in items if item.matched_product_id is not None),
        key=lambda item: (item.matched_product_id, item.line_no),
    )
    for item in stock_items:
        # qty = qty + n is done BY THE DATABASE: safe even while a sale
        # changes the same product at the same moment (no read-then-write).
        db.execute(
            update(Product)
            .where(Product.id == item.matched_product_id)
            .values(qty=Product.qty + item.qty)
        )
        db.add(
            StockMovement(
                product_id=item.matched_product_id,
                change=item.qty,
                reason="invoice",
                invoice_id=claim.invoice_id,
                invoice_item_id=item.id,
            )
        )
    db.commit()

    logger.info(
        "invoice processed",
        extra={
            **log,
            "lines": len(items),
            "matched": len(stock_items),
            "needs_review": len(items) - len(stock_items),
        },
    )
    return Result.PROCESSED


def _mark_failed(db: Session, claim: Claim, reason: str) -> Result:
    """Permanent problem: record why, so GET /invoices/{id} explains it."""
    changed = db.execute(
        update(Invoice)
        .where(_still_ours(claim))
        .values(status="failed", error_message=reason[:ERROR_MESSAGE_MAX])
    ).rowcount
    db.commit()
    log = {"invoice_id": claim.invoice_id, "attempt": claim.attempt}
    if changed == 0:
        logger.warning("lease lost before marking failed", extra=log)
        return Result.LOST_LEASE
    logger.warning("invoice failed", extra={**log, "reason": reason})
    return Result.FAILED


def _release(db: Session, claim: Claim) -> None:
    """Temporary problem: hand the invoice back, so the next delivery can claim it."""
    db.execute(
        update(Invoice)
        .where(_still_ours(claim))
        .values(status="uploaded", processing_started_at=None)
    )
    db.commit()
