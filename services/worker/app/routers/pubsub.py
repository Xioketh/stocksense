"""Endpoint that Pub/Sub PUSHES messages to.

The HTTP status code is our answer to Pub/Sub:
- 2xx            -> "acknowledged, done" (Pub/Sub forgets the message)
- anything else  -> "not done" (Pub/Sub delivers it again later)

So: return 200 for everything retrying can't fix or doesn't need (processed,
failed with a reason, duplicate, unknown, irrelevant), and 503 ONLY when a
later delivery could succeed (Gemini busy, another worker on it, database
down - see main.py).
"""

import logging

from fastapi import APIRouter, Depends, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.extraction import InvoiceExtractor, get_extractor
from app.schemas import Outcome, PushEnvelope, PushResult, StorageEvent
from app.services.invoice_events import handle_storage_event
from app.services.invoice_processing import Result, process_invoice
from app.storage import InvoiceFiles, get_invoice_files

router = APIRouter(tags=["pubsub"])
logger = logging.getLogger(__name__)

# Results that mean "not finished yet, deliver this message again later".
TRY_AGAIN_LATER = {Result.RETRY_LATER, Result.IN_PROGRESS}


@router.post(
    "/pubsub/invoice-uploaded", response_model=PushResult, response_model_exclude_none=True
)
def invoice_uploaded(
    envelope: PushEnvelope,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    files: InvoiceFiles = Depends(get_invoice_files),
    extractor: InvoiceExtractor = Depends(get_extractor),
) -> PushResult:
    msg = envelope.message
    attempt = envelope.delivery_attempt
    logger.info(
        "message received", extra={"message_id": msg.message_id, "delivery_attempt": attempt}
    )

    try:
        event = StorageEvent.model_validate(msg.attributes)
    except ValidationError:
        # Not a Cloud Storage notification. Retrying won't change that: ack it.
        logger.error("message is missing storage attributes", extra={"message_id": msg.message_id})
        return PushResult(outcome=Outcome.IGNORED)

    # Step 1: mark the invoice 'uploaded' (Phase 3).
    outcome, invoice_id = handle_storage_event(db, event, expected_bucket=settings.invoices_bucket)
    if invoice_id is None:  # unknown object or irrelevant event: nothing to process
        return PushResult(outcome=outcome)

    # Step 2: read it with Gemini and update stock (Phase 4).
    # deliveryAttempt is only sent when the subscription has a dead-letter policy.
    final_delivery = attempt is not None and attempt >= settings.max_delivery_attempts
    result = process_invoice(
        db,
        invoice_id,
        files=files,
        extractor=extractor,
        lease_seconds=settings.processing_lease_seconds,
        final_delivery=final_delivery,
    )

    if result in TRY_AGAIN_LATER:
        response.status_code = 503  # "not done": Pub/Sub redelivers with backoff
    logger.info(
        "message handled",
        extra={"message_id": msg.message_id, "invoice_id": invoice_id, "result": result},
    )
    return PushResult(outcome=outcome, processing=result)