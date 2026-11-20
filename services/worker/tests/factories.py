"""Helpers that build test data. (Kept out of conftest.py on purpose:
conftest is for fixtures, and importing from it is a known pytest gotcha.)"""


def make_envelope(
    object_id: str = "invoices/abc123.pdf",
    event_type: str = "OBJECT_FINALIZE",
    bucket_id: str = "test-invoices",
    message_id: str = "1001",
) -> dict:
    """Build a request body exactly like a Pub/Sub push delivery."""
    return {
        "message": {
            "attributes": {
                "eventType": event_type,
                "bucketId": bucket_id,
                "objectId": object_id,
                "objectGeneration": "1732071605123456",
                "payloadFormat": "JSON_API_V1",
            },
            "data": "e30=",  # base64 of "{}" (the worker doesn't read it yet)
            "messageId": message_id,
            "publishTime": "2026-11-20T10:25:36.123Z",
        },
        "subscription": "projects/test/subscriptions/invoice-uploaded-worker",
        "deliveryAttempt": 1,
    }
