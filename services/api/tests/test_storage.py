"""Unit tests for app/storage.py, using mocks instead of real Google Cloud."""

from unittest.mock import MagicMock, patch

import pytest

from app import storage
from app.storage import GcsUploadSigner, get_upload_signer


def test_gcs_signer_uses_iam_signing_not_a_key_file():
    # Fake Cloud Run credentials: a token and an email, but no private key.
    creds = MagicMock(valid=False, token="fake-token", service_account_email="api-sa@x.iam")

    with (
        patch.object(storage.google.auth, "default", return_value=(creds, "my-project")),
        patch.object(storage.gcs, "Client") as client_class,
    ):
        blob = client_class.return_value.bucket.return_value.blob.return_value
        blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"

        signer = GcsUploadSigner("my-bucket", ttl_seconds=900, max_bytes=100)
        result = signer.create_upload_url("invoices/a.pdf", "application/pdf")

    creds.refresh.assert_called_once()  # got a fresh token first
    kwargs = blob.generate_signed_url.call_args.kwargs
    assert kwargs["version"] == "v4"
    assert kwargs["method"] == "PUT"
    assert kwargs["content_type"] == "application/pdf"
    assert kwargs["service_account_email"] == "api-sa@x.iam"  # -> IAM signBlob
    assert kwargs["access_token"] == "fake-token"
    assert result.url == "https://storage.googleapis.com/signed"
    assert result.headers == {
        "Content-Type": "application/pdf",
        "X-Goog-Content-Length-Range": "0,100",
    }


def test_fake_backend_is_refused_on_cloud_run(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("STORAGE_BACKEND", "fake")
    storage.get_settings.cache_clear()
    get_upload_signer.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="not allowed"):
            get_upload_signer()
    finally:
        # Put the cached test settings back for the other tests.
        monkeypatch.undo()
        storage.get_settings.cache_clear()
        get_upload_signer.cache_clear()