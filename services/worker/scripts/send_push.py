"""Pretend to be Pub/Sub: send one "file uploaded" push to the LOCAL worker.

On Cloud Run, the bucket notification + push subscription do this. Locally
there's no real bucket, so after POST /invoices/upload-url you run this with
the upload_url (or just the object name) the API gave you.

Only the Python standard library, so it runs with any Python:
    python services/worker/scripts/send_push.py UPLOAD_URL_OR_OBJECT_NAME
    python services/worker/scripts/send_push.py invoices/abc.pdf --attempt 5
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from urllib.parse import urlparse

LOCAL_BUCKET = "local-invoices"  # docker-compose: INVOICES_BUCKET for the worker


def object_name(value: str) -> str:
    """'https://fake-gcs.invalid/local-invoices/invoices/x.pdf?...' -> 'invoices/x.pdf'."""
    if not value.startswith("http"):
        return value
    path = urlparse(value).path.lstrip("/")  # 'local-invoices/invoices/x.pdf'
    return path.split("/", 1)[1]  # drop the bucket name


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a fake Pub/Sub push to the worker.")
    parser.add_argument("upload", help="upload_url from the API, or an object name")
    parser.add_argument("--worker", default="http://localhost:8001")
    parser.add_argument("--attempt", type=int, default=1, help="deliveryAttempt (5 = last)")
    args = parser.parse_args()

    envelope = {
        "message": {
            "attributes": {
                "eventType": "OBJECT_FINALIZE",
                "bucketId": LOCAL_BUCKET,
                "objectId": object_name(args.upload),
                "payloadFormat": "JSON_API_V1",
            },
            "data": "e30=",
            "messageId": f"local-{datetime.now(UTC):%H%M%S}",
            "publishTime": datetime.now(UTC).isoformat(),
        },
        "subscription": "projects/local/subscriptions/invoice-uploaded-worker",
        "deliveryAttempt": args.attempt,
    }
    request = urllib.request.Request(
        f"{args.worker}/pubsub/invoice-uploaded",
        data=json.dumps(envelope).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(f"POST {request.full_url}  objectId={envelope['message']['attributes']['objectId']}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, body = response.status, response.read().decode()
    except urllib.error.HTTPError as error:  # 4xx/5xx still have a body
        status, body = error.code, error.read().decode()

    meaning = "ack (Pub/Sub would forget it)" if 200 <= status < 300 else "Pub/Sub would RETRY"
    print(f"{status}  {body}\n-> {meaning}")
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())