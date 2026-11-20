"""Endpoint that Pub/Sub PUSHES messages to.

The HTTP status code is our answer to Pub/Sub:
- 2xx            -> "acknowledged, done" (Pub/Sub forgets the message)
- anything else  -> "not done" (Pub/Sub delivers it again later)

So: return 200 for everything retrying can't fix (handled, duplicate,
unknown, irrelevant), and an error ONLY when a retry could succeed
(e.g. the database is down -> 503, see main.py).
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.schemas import Outcome, PushEnvelope, PushResult, StorageEvent
from app.services.invoice_events import handle_storage_event

router = APIRouter(tags=["pubsub"])
logger = logging.getLogger(__name__)


@router.post("/pubsub/invoice-uploaded", response_model=PushResult)
def invoice_uploaded(
    envelope: PushEnvelope,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PushResult:
    msg = envelope.message
    logger.info(
        "message received",
        extra={"message_id": msg.message_id, "delivery_attempt": envelope.delivery_attempt},
    )

    try:
        event = StorageEvent.model_validate(msg.attributes)
    except ValidationError:
        # Not a Cloud Storage notification. Retrying won't change that: ack it.
        logger.error("message is missing storage attributes", extra={"message_id": msg.message_id})
        return PushResult(outcome=Outcome.IGNORED)

    outcome = handle_storage_event(db, event, expected_bucket=settings.invoices_bucket)
    return PushResult(outcome=outcome)
