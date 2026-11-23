"""Unit tests for reading files from Cloud Storage, with a stub bucket."""

from types import SimpleNamespace

import pytest
from google.api_core import exceptions as google_errors

from app.storage import GcsInvoiceFiles, InvoiceFileError, StorageUnavailable

MAX_BYTES = 1000


def files_with(blob=None, error: Exception | None = None) -> GcsInvoiceFiles:
    """A GcsInvoiceFiles whose bucket returns `blob` (or raises `error`)."""

    def get_blob(name, timeout):
        if error is not None:
            raise error
        return blob

    return GcsInvoiceFiles(SimpleNamespace(get_blob=get_blob), max_bytes=MAX_BYTES)


def fake_blob(size: int, content: bytes = b"%PDF"):
    return SimpleNamespace(
        size=size, generation=7, download_as_bytes=lambda timeout, if_generation_match: content
    )


def test_reads_the_file():
    assert files_with(fake_blob(size=4)).read("invoices/a.pdf") == b"%PDF"


def test_missing_file_is_permanent():
    with pytest.raises(InvoiceFileError, match="not in the bucket"):
        files_with(blob=None).read("invoices/a.pdf")


def test_too_large_file_is_permanent_and_not_downloaded():
    def must_not_download(**kwargs):
        raise AssertionError("downloaded a file that is too large")

    big = SimpleNamespace(size=MAX_BYTES + 1, generation=7, download_as_bytes=must_not_download)

    with pytest.raises(InvoiceFileError, match="too large"):
        files_with(big).read("invoices/a.pdf")


@pytest.mark.parametrize(
    "error",
    [
        google_errors.ServiceUnavailable("storage is down"),
        google_errors.Forbidden("worker-sa lost its role"),  # fixable: try later
    ],
)
def test_storage_problems_are_temporary(error):
    with pytest.raises(StorageUnavailable):
        files_with(error=error).read("invoices/a.pdf")
