"""Shared test setup for the worker.

The worker gets its OWN test database (stocksense_worker_test) on the same
db-test container, so its tests and the API's tests never touch each
other's tables.
"""

import os

TEST_DB_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_DB_PORT = os.getenv("TEST_DB_PORT", "5433")
TEST_DB_NAME = "stocksense_worker_test"

# Must be set BEFORE importing the app (the engine is created at import time).
os.environ["DB_HOST"] = TEST_DB_HOST
os.environ["DB_PORT"] = TEST_DB_PORT
os.environ["DB_NAME"] = TEST_DB_NAME
os.environ["DB_USER"] = "stocksense"
os.environ["DB_PASSWORD"] = "test-password"
os.environ["INVOICES_BUCKET"] = "test-invoices"
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Invoice  # noqa: E402


def _create_test_database_if_missing() -> None:
    """Connect to the default 'postgres' database and create ours once."""
    admin = create_engine(
        f"postgresql+psycopg://stocksense:test-password@{TEST_DB_HOST}:{TEST_DB_PORT}/postgres",
        isolation_level="AUTOCOMMIT",  # CREATE DATABASE can't run inside a transaction
    )
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    _create_test_database_if_missing()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)  # only the columns the worker maps
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_tables():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE invoices RESTART IDENTITY"))


@pytest.fixture
def client() -> TestClient:
    # No API key: on Cloud Run, IAM checks Pub/Sub's identity before
    # the request ever reaches our code.
    return TestClient(app)


@pytest.fixture
def pending_invoice() -> Invoice:
    """An invoice row like the API creates in POST /invoices/upload-url."""
    with SessionLocal() as db:
        invoice = Invoice(gcs_path="invoices/abc123.pdf", status="pending_upload")
        db.add(invoice)
        db.commit()
        return invoice
