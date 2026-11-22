"""Shared test setup for the worker.

The worker gets its OWN test database (stocksense_worker_test) on the same
db-test container, so its tests and the API's tests never touch each
other's tables.

The API OWNS the schema, so this database is built by running the API's
real Alembic migrations, NOT create_all() on the worker's small models.
That way the tests see exactly the tables production has: every column,
every NOT NULL, CHECK and UNIQUE constraint. If an API migration ever
breaks the worker, these tests fail in CI before anything is deployed.
"""

import os
import subprocess
import sys
from pathlib import Path

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

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Invoice  # noqa: E402
from tests.factories import insert_invoice  # noqa: E402

# services/worker/tests/conftest.py -> parents[2] is services/
API_DIR = Path(__file__).resolve().parents[2] / "api"

# Every table the app uses. NOT alembic_version: that one records which
# migrations ran, and emptying it would make the schema look un-migrated.
APP_TABLES = "products, stock_movements, invoices, invoice_items"


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


def _reset_schema() -> None:
    """Delete every table (including alembic_version), so migrations start from zero."""
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _run_api_migrations() -> None:
    """Run 'alembic upgrade head' from services/api against the worker's test database.

    It runs as a SEPARATE process on purpose: the API and the worker both
    have a package called "app", so the API's migration code can't be
    imported into this (the worker's) Python process.
    """
    env = {
        **os.environ,  # DB_HOST, DB_NAME, ... set above -> the worker's test database
        "API_KEY": "not-used-by-migrations",  # the API's settings require it
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.exit(f"API migrations failed:\n{result.stderr}", returncode=1)


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    # Safety check: refuse to wipe anything that isn't a test database.
    assert engine.url.database.endswith("_test"), "Tests must use a *_test database!"
    _create_test_database_if_missing()
    _reset_schema()
    _run_api_migrations()
    yield
    # No teardown: the tables stay, so you can inspect them with psql
    # after a failing run. The next run resets the schema anyway.


@pytest.fixture(autouse=True)
def clean_tables():
    """Empty the tables after every test, so each test starts fresh."""
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {APP_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def client() -> TestClient:
    # No API key: on Cloud Run, IAM checks Pub/Sub's identity before
    # the request ever reaches our code.
    return TestClient(app)


@pytest.fixture
def pending_invoice() -> Invoice:
    """An invoice row like the API creates in POST /invoices/upload-url."""
    invoice_id = insert_invoice(gcs_path="invoices/abc123.pdf", status="pending_upload")
    with SessionLocal() as db:
        return db.get(Invoice, invoice_id)
