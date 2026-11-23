"""Reading uploaded invoice files from Cloud Storage.

Same pattern as extraction: a small interface (InvoiceFiles), a real
implementation (GcsInvoiceFiles) and a fake one (FakeInvoiceFiles).
"""

import logging
from functools import lru_cache
from typing import Protocol

import requests
from google.api_core import exceptions as google_errors

from app.config import get_settings

logger = logging.getLogger(__name__)


class InvoiceFileError(Exception):
    """PERMANENT: the file is gone or unusable. Retrying won't help."""


class StorageUnavailable(Exception):
    """TEMPORARY: Cloud Storage didn't answer properly. Try again later."""


class InvoiceFiles(Protocol):
    def read(self, gcs_path: str) -> bytes:
        """Return the file's bytes. Raises InvoiceFileError or StorageUnavailable."""
        ...


class GcsInvoiceFiles:
    """Downloads with worker-sa's identity (roles/storage.objectViewer on the bucket)."""

    def __init__(self, bucket, max_bytes: int) -> None:
        self._bucket = bucket
        self._max_bytes = max_bytes

    def read(self, gcs_path: str) -> bytes:
        try:
            # Metadata first: check the size BEFORE downloading anything.
            blob = self._bucket.get_blob(gcs_path, timeout=10)
            if blob is None:
                raise InvoiceFileError("The file is not in the bucket (deleted?)")
            if blob.size > self._max_bytes:
                raise InvoiceFileError(
                    f"The file is too large ({blob.size} bytes, limit {self._max_bytes})"
                )
            # if_generation_match: download exactly the version we just checked.
            return blob.download_as_bytes(timeout=30, if_generation_match=blob.generation)
        except google_errors.NotFound as exc:  # deleted between the two calls
            raise InvoiceFileError("The file is not in the bucket (deleted?)") from exc
        except (
            google_errors.GoogleAPICallError,  # 403 (IAM), 429, 5xx, ...
            google_errors.RetryError,  # the library's own retries gave up
            requests.RequestException,  # timeouts, connection problems
        ) as exc:
            logger.error("cloud storage error", extra={"error": repr(exc)})
            raise StorageUnavailable(f"Could not read the file: {type(exc).__name__}") from exc


class FakeInvoiceFiles:
    """No Google Cloud. Tests choose the files; locally every path gets `default`."""

    def __init__(self, files: dict[str, bytes] | None = None, default: bytes | None = None):
        self.files = files or {}
        self.default = default

    def read(self, gcs_path: str) -> bytes:
        if gcs_path in self.files:
            return self.files[gcs_path]
        if self.default is not None:
            return self.default
        raise InvoiceFileError("The file is not in the bucket (deleted?)")


@lru_cache
def get_invoice_files() -> InvoiceFiles:
    """Build the file reader once, on first use (FastAPI dependency)."""
    settings = get_settings()

    if settings.storage_backend == "fake":
        if settings.app_env in ("dev", "prod"):
            raise RuntimeError("STORAGE_BACKEND=fake is not allowed when APP_ENV is dev/prod")
        logger.warning("using FAKE invoice files (local/test only)")
        return FakeInvoiceFiles(default=b"%PDF-1.7 local fake invoice")

    from google.cloud import storage  # imported here: only needed on Cloud Run

    bucket = storage.Client().bucket(settings.invoices_bucket)
    return GcsInvoiceFiles(bucket, max_bytes=settings.max_invoice_bytes)