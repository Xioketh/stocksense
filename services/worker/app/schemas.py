"""Shapes of the data the worker receives.

Pub/Sub push wraps every message in an "envelope" (a JSON body):

{
  "message": {
    "attributes": {"eventType": "OBJECT_FINALIZE", "bucketId": "...", "objectId": "...", ...},
    "data": "<base64 JSON with the object's metadata>",
    "messageId": "1234567890",
    "publishTime": "2026-11-20T10:25:36.123Z"
  },
  "subscription": "projects/<project>/subscriptions/<name>",
  "deliveryAttempt": 1        <- only when a dead-letter policy is set
}
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.services.invoice_processing import Result


class PubSubMessage(BaseModel):
    message_id: str = Field(alias="messageId")
    publish_time: datetime | None = Field(default=None, alias="publishTime")
    attributes: dict[str, str] = Field(default_factory=dict)
    data: str | None = None  # base64; not needed in Phase 3


class PushEnvelope(BaseModel):
    message: PubSubMessage
    subscription: str
    delivery_attempt: int | None = Field(default=None, alias="deliveryAttempt")


class StorageEvent(BaseModel):
    """The Cloud Storage facts, taken from the message ATTRIBUTES."""

    event_type: str = Field(alias="eventType")
    bucket_id: str = Field(alias="bucketId")
    object_id: str = Field(alias="objectId")  # e.g. "invoices/3f2a....pdf"
    object_generation: str | None = Field(default=None, alias="objectGeneration")


class Outcome(StrEnum):
    """Step 1 of a message: what happened to the invoice's 'uploaded' status."""

    MARKED_UPLOADED = "marked_uploaded"  # first delivery: status changed
    DUPLICATE = "duplicate"  # marked before (a redelivery); processing still decides
    UNKNOWN_OBJECT = "unknown_object"  # no invoice row has this file
    IGNORED = "ignored"  # not an event we care about


class PushResult(BaseModel):
    outcome: Outcome
    # Step 2: what processing did (None when there was no invoice to process).
    processing: Result | None = None
