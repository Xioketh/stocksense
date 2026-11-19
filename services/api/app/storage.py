"""Signed upload URLs for the invoices bucket.

One small interface (UploadSigner), two implementations:
- GcsUploadSigner:  real V4 signed URLs. On Cloud Run there is no key file,
                    so the signature is made by the IAM signBlob API.
- FakeUploadSigner: fake URLs for local development and tests (no Google Cloud).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol

import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage as gcs

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignedUpload:
    url: str
    headers: dict[str, str]  # the client MUST send exactly these headers with the PUT
    expires_at: datetime


class UploadSigner(Protocol):
    def create_upload_url(self, object_name: str, content_type: str) -> SignedUpload: ...


def required_upload_headers(content_type: str, max_bytes: int) -> dict[str, str]:
    """Headers that are part of the signature.

    Because they are signed, the client can't change them:
    - Content-Type: can't upload an .exe while claiming it's a PDF
    - X-Goog-Content-Length-Range: Cloud Storage rejects files bigger than max_bytes
    """
    return {
        "Content-Type": content_type,
        "X-Goog-Content-Length-Range": f"0,{max_bytes}",
    }


class GcsUploadSigner:
    def __init__(self, bucket_name: str, ttl_seconds: int, max_bytes: int) -> None:
        # Application Default Credentials (ADC): on Cloud Run these are the
        # service account's credentials from the metadata server.
        self._credentials, project = google.auth.default()
        self._bucket = gcs.Client(credentials=self._credentials, project=project).bucket(
            bucket_name
        )
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_bytes = max_bytes

    def create_upload_url(self, object_name: str, content_type: str) -> SignedUpload:
        # Cloud Run credentials have an access token but NO private key.
        # Refreshing gives us a fresh token and the real service account email.
        if not self._credentials.valid:
            self._credentials.refresh(Request())

        headers = required_upload_headers(content_type, self._max_bytes)
        url = self._bucket.blob(object_name).generate_signed_url(
            version="v4",
            method="PUT",
            expiration=self._ttl,
            content_type=headers["Content-Type"],
            headers={"X-Goog-Content-Length-Range": headers["X-Goog-Content-Length-Range"]},
            # These two make the library call IAM signBlob instead of
            # looking for a private key (which we don't have, on purpose).
            service_account_email=self._credentials.service_account_email,
            access_token=self._credentials.token,
        )
        return SignedUpload(url=url, headers=headers, expires_at=datetime.now(UTC) + self._ttl)


class FakeUploadSigner:
    """Returns a URL that looks real but goes nowhere. For local dev and tests."""

    def __init__(self, bucket_name: str, ttl_seconds: int, max_bytes: int) -> None:
        self._bucket_name = bucket_name or "local-invoices"
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_bytes = max_bytes

    def create_upload_url(self, object_name: str, content_type: str) -> SignedUpload:
        return SignedUpload(
            url=f"https://fake-gcs.invalid/{self._bucket_name}/{object_name}?signature=fake",
            headers=required_upload_headers(content_type, self._max_bytes),
            expires_at=datetime.now(UTC) + self._ttl,
        )


@lru_cache
def get_upload_signer() -> UploadSigner:
    """FastAPI dependency: build the signer once, on first use."""
    settings = get_settings()
    args = (settings.invoices_bucket, settings.upload_url_ttl_seconds, settings.max_upload_bytes)

    if settings.storage_backend == "fake":
        # Safety net: a forgotten env var on Cloud Run must fail loudly,
        # not hand out fake URLs.
        if settings.app_env in ("dev", "prod"):
            raise RuntimeError("STORAGE_BACKEND=fake is not allowed when APP_ENV is dev/prod")
        logger.warning("using FAKE upload signer (local/test only)")
        return FakeUploadSigner(*args)

    if not settings.invoices_bucket:
        raise RuntimeError("INVOICES_BUCKET must be set when STORAGE_BACKEND=gcs")
    logger.info("using GCS upload signer", extra={"bucket": settings.invoices_bucket})
    return GcsUploadSigner(*args)