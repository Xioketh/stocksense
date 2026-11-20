"""What the worker does when Cloud Storage says "a new file arrived"."""

import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Invoice
from app.schemas import Outcome, StorageEvent

logger = logging.getLogger(__name__)


def handle_storage_event(db: Session, event: StorageEvent, expected_bucket: str) -> Outcome:
    log = {"object_id": event.object_id, "generation": event.object_generation}

    # 1. Only react to new files in OUR bucket. Anything else: acknowledge
    #    and move on, because retrying will never make it valid.
    if event.event_type != "OBJECT_FINALIZE":
        logger.info("ignoring event type", extra={**log, "event_type": event.event_type})
        return Outcome.IGNORED
    if event.bucket_id != expected_bucket:
        logger.warning("event from unexpected bucket", extra={**log, "bucket": event.bucket_id})
        return Outcome.IGNORED

    # 2. Idempotent update: ONE statement that changes the row only if it is
    #    still 'pending_upload'. The database does the check and the change
    #    together, so two deliveries of the same message (even at the same
    #    moment) can never both "win".
    result = db.execute(
        update(Invoice)
        .where(Invoice.gcs_path == event.object_id, Invoice.status == "pending_upload")
        .values(status="uploaded", uploaded_at=func.now())
    )
    db.commit()

    if result.rowcount == 1:
        logger.info("invoice marked uploaded", extra=log)
        return Outcome.MARKED_UPLOADED

    # 3. Nothing changed. Find out why, for the logs.
    status = db.scalar(select(Invoice.status).where(Invoice.gcs_path == event.object_id))
    if status is None:
        logger.warning("no invoice for this object", extra=log)
        return Outcome.UNKNOWN_OBJECT

    logger.info("duplicate delivery, already handled", extra={**log, "status": status})
    return Outcome.DUPLICATE
