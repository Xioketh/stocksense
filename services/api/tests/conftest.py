"""Shared test setup. pytest loads this file automatically before any test.

Tests use a SEPARATE Postgres (the "db-test" container on port 5433),
so they can never touch your real data.
"""

import os

# These must be set BEFORE importing the app, because app.db creates the
# database engine at import time using these settings.
os.environ["DB_HOST"] = os.getenv("TEST_DB_HOST", "localhost")
os.environ["DB_PORT"] = os.getenv("TEST_DB_PORT", "5433")
os.environ["DB_NAME"] = "stocksense_test"
os.environ["DB_USER"] = "stocksense"
os.environ["DB_PASSWORD"] = "test-password"
os.environ["API_KEY"] = "test-api-key"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["APP_ENV"] = "test"
os.environ["STORAGE_BACKEND"] = "fake"  # never call real Cloud Storage from tests
os.environ["INVOICES_BUCKET"] = "test-invoices"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

TEST_API_KEY = "test-api-key"


@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once for the whole test run, drop them at the end."""
    # Safety check: refuse to run against anything that isn't a test database.
    assert get_settings().db_name.endswith("_test"), "Tests must use a *_test database!"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def clean_tables():
    """Empty the tables after every test, so each test starts fresh."""
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE products, stock_movements, invoices, invoice_items "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def client() -> TestClient:
    """A test client that already sends the correct API key."""
    return TestClient(app, headers={"X-API-Key": TEST_API_KEY})


@pytest.fixture
def anon_client() -> TestClient:
    """A test client WITHOUT an API key (to test that auth works)."""
    return TestClient(app)


@pytest.fixture
def rice(client: TestClient) -> dict:
    """Create the 'Rice 5kg' product from the user story and return it."""
    response = client.post(
        "/products",
        json={"sku": "RICE-5", "name": "Rice 5kg", "qty": 20, "low_stock_threshold": 5},
    )
    assert response.status_code == 201
    return response.json()
