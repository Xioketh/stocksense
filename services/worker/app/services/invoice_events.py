"""What the worker does when Cloud Storage says "a new file arrived"."""

import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Invoice
from app.schemas import Outcome, StorageEvent

logger = logging.getLogger(__name__)


def handle_storage_event(
    db: Session, event: StorageEvent, expected_bucket: str
) -> tuple[Outcome, int | None]:
    """Mark the invoice 'uploaded'. Returns the outcome and the invoice id
    (None when there is no invoice to process)."""
    log = {"object_id": event.object_id, "generation": event.object_generation}

    # 1. Only react to new files in OUR bucket. Anything else: acknowledge
    #    and move on, because retrying will never make it valid.
    if event.event_type != "OBJECT_FINALIZE":
        logger.info("ignoring event type", extra={**log, "event_type": event.event_type})
        return Outcome.IGNORED, None
    if event.bucket_id != expected_bucket:
        logger.warning("event from unexpected bucket", extra={**log, "bucket": event.bucket_id})
        return Outcome.IGNORED, None

    # 2. Idempotent update: ONE statement that changes the row only if it is
    #    still 'pending_upload'. The database does the check and the change
    #    together, so two deliveries of the same message (even at the same
    #    moment) can never both "win".
    invoice_id = db.scalar(
        update(Invoice)
        .where(Invoice.gcs_path == event.object_id, Invoice.status == "pending_upload")
        .values(status="uploaded", uploaded_at=func.now())
        .returning(Invoice.id)
    )
    db.commit()

    if invoice_id is not None:
        logger.info("invoice marked uploaded", extra={**log, "invoice_id": invoice_id})
        return Outcome.MARKED_UPLOADED, invoice_id

    # 3. Nothing changed. Either there is no such invoice, or it was marked
    #    before (a redelivery). A redelivery may still need processing, e.g.
    #    when the last attempt hit a temporary error: processing decides.
    row = db.execute(
        select(Invoice.id, Invoice.status).where(Invoice.gcs_path == event.object_id)
    ).one_or_none()
    if row is None:
        logger.warning("no invoice for this object", extra=log)
        return Outcome.UNKNOWN_OBJECT, None

    logger.info("invoice was already marked uploaded", extra={**log, "status": row.status})
    return Outcome.DUPLICATE, row.id