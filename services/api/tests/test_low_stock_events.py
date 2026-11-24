"""LowStock events: when they are published, and what happens if publishing fails.

No real Pub/Sub here: FastAPI's dependency_overrides swaps the publisher
for a FakePublisher (or a broken one), only for these tests.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app import events
from app.db import SessionLocal
from app.events import FakePublisher, LowStockEvent, PubSubPublisher, get_event_publisher
from app.main import app
from app.models import StockMovement
from app.services.stock_rules import crossed_into_low_stock

# ---------------------------------------------------------------- unit tests


@pytest.mark.parametrize(
    ("old_qty", "new_qty", "threshold", "expected"),
    [
        (20, 4, 5, True),  # OK -> low: alert (Nimal's story)
        (5, 4, 5, True),  # exactly at the limit is still OK, 4 is low: alert
        (4, 2, 5, False),  # already low before this sale: no second alert
        (20, 10, 5, False),  # still above the limit: no alert
        (20, 0, 0, False),  # threshold 0 means "never alert"
    ],
)
def test_crossed_into_low_stock(old_qty, new_qty, threshold, expected):
    assert crossed_into_low_stock(old_qty, new_qty, threshold) is expected


def test_pubsub_publisher_sends_json_with_attributes():
    with patch.object(events.pubsub_v1, "PublisherClient") as client_class:
        client = client_class.return_value
        client.topic_path.return_value = "projects/p/topics/low-stock"
        client.publish.return_value.result.return_value = "msg-123"

        publisher = PubSubPublisher("p", "low-stock", env="dev", timeout_seconds=5)
        event = LowStockEvent(sku="RICE-5", name="Rice 5kg", qty=4, threshold=5)
        message_id = publisher.publish_low_stock(event)

    assert message_id == "msg-123"
    topic, data = client.publish.call_args.args
    assert topic == "projects/p/topics/low-stock"
    assert b'"sku": "RICE-5"' in data
    assert client.publish.call_args.kwargs == {"event_type": "LowStock", "env": "dev"}
    # We waited for Pub/Sub's answer, with a time limit
    client.publish.return_value.result.assert_called_once_with(timeout=5)


# ---------------------------------------------------------------- API tests


@pytest.fixture
def fake_publisher():
    fake = FakePublisher()
    app.dependency_overrides[get_event_publisher] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_event_publisher)


def test_sale_that_crosses_the_limit_publishes_one_event(client, rice, fake_publisher):
    # Rice: 20 in stock, alert below 5. Sell 16 -> 4 left.
    response = client.post("/stock/out", json={"sku": "RICE-5", "qty": 16})

    assert response.status_code == 200
    assert len(fake_publisher.events) == 1
    event = fake_publisher.events[0]
    assert (event.sku, event.name, event.qty, event.threshold) == ("RICE-5", "Rice 5kg", 4, 5)


def test_no_second_event_while_stock_stays_low(client, rice, fake_publisher):
    client.post("/stock/out", json={"sku": "RICE-5", "qty": 16})  # 20 -> 4: alert
    client.post("/stock/out", json={"sku": "RICE-5", "qty": 1})  # 4 -> 3: still low

    assert len(fake_publisher.events) == 1


def test_no_event_while_stock_is_above_the_limit(client, rice, fake_publisher):
    client.post("/stock/out", json={"sku": "RICE-5", "qty": 2})  # 20 -> 18

    assert fake_publisher.events == []


def test_publish_failure_does_not_undo_the_sale(client, rice):
    broken = MagicMock()
    broken.publish_low_stock.side_effect = TimeoutError("Pub/Sub did not answer")
    app.dependency_overrides[get_event_publisher] = lambda: broken
    try:
        response = client.post("/stock/out", json={"sku": "RICE-5", "qty": 16})
    finally:
        app.dependency_overrides.pop(get_event_publisher)

    # The sale is committed and reported as a success...
    assert response.status_code == 200
    assert response.json()["new_qty"] == 4
    broken.publish_low_stock.assert_called_once()
    # ...and recorded exactly once.
    with SessionLocal() as db:
        assert len(db.scalars(select(StockMovement)).all()) == 1


def test_fake_publisher_is_refused_on_cloud_run(monkeypatch):
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("EVENTS_BACKEND", "fake")
    events.get_settings.cache_clear()
    get_event_publisher.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="not allowed"):
            get_event_publisher()
    finally:
        # Put the cached test settings back for the other tests.
        monkeypatch.undo()
        events.get_settings.cache_clear()
        get_event_publisher.cache_clear()
