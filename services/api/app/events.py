"""Publish LowStock events to Pub/Sub.

Same pattern as storage.py: one small interface, two implementations.
- PubSubPublisher: publishes to the real "low-stock" topic.
- FakePublisher:   keeps events in a list (local development and tests).

The API only announces "this product is low". It doesn't know who listens
or how the email is sent: that is the notifier's job. That separation is
the point of using Pub/Sub here.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Protocol

from google.cloud import pubsub_v1

from app.config import get_settings

logger = logging.getLogger(__name__)

LOW_STOCK = "LowStock"


@dataclass(frozen=True)
class LowStockEvent:
    sku: str
    name: str
    qty: int
    threshold: int
    # A unique id per event: the notifier logs it, so a duplicate delivery
    # (Pub/Sub is at-least-once) can be recognised in the logs.
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_bytes(self) -> bytes:
        """Pub/Sub message data is bytes. We send JSON."""
        return json.dumps(asdict(self)).encode("utf-8")


class EventPublisher(Protocol):
    def publish_low_stock(self, event: LowStockEvent) -> str:
        """Publish the event and return the Pub/Sub message id."""
        ...


class PubSubPublisher:
    def __init__(self, project_id: str, topic: str, env: str, timeout_seconds: float) -> None:
        # Uses Application Default Credentials: on Cloud Run, the api-sa.
        self._client = pubsub_v1.PublisherClient()
        self._topic_path = self._client.topic_path(project_id, topic)
        self._env = env
        self._timeout = timeout_seconds

    def publish_low_stock(self, event: LowStockEvent) -> str:
        future = self._client.publish(
            self._topic_path,
            event.to_bytes(),
            # Attributes: small string key/values OUTSIDE the data. Subscribers
            # can filter on them without parsing the JSON body.
            event_type=LOW_STOCK,
            env=self._env,
        )
        # Wait for Pub/Sub to confirm, INSIDE the request. On Cloud Run the
        # CPU is throttled once the response is sent, so a publish left
        # running "in the background" may never finish.
        return future.result(timeout=self._timeout)


class FakePublisher:
    """Remembers published events instead of sending them. No Google Cloud needed."""

    def __init__(self) -> None:
        self.events: list[LowStockEvent] = []

    def publish_low_stock(self, event: LowStockEvent) -> str:
        self.events.append(event)
        return f"fake-{len(self.events)}"


@lru_cache
def get_event_publisher() -> EventPublisher:
    """FastAPI dependency: build the publisher once, on first use."""
    settings = get_settings()

    if settings.events_backend == "fake":
        # Same safety net as the upload signer: a forgotten env var on
        # Cloud Run must fail loudly, not silently drop every alert.
        if settings.app_env in ("dev", "prod"):
            raise RuntimeError("EVENTS_BACKEND=fake is not allowed when APP_ENV is dev/prod")
        logger.warning("using FAKE event publisher (local/test only)")
        return FakePublisher()

    if not settings.google_cloud_project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT must be set when EVENTS_BACKEND=pubsub")
    logger.info(
        "using Pub/Sub event publisher",
        extra={"project": settings.google_cloud_project, "topic": settings.low_stock_topic},
    )
    return PubSubPublisher(
        project_id=settings.google_cloud_project,
        topic=settings.low_stock_topic,
        env=settings.app_env,
        timeout_seconds=settings.publish_timeout_seconds,
    )
