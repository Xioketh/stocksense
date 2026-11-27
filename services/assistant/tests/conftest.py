"""Shared test setup for the assistant.

A2 has no database or model calls yet, so tests only need settings.
Every value is fake: tests must never call Gemini, LangSmith or the real API.
"""

import os

# Must be set BEFORE importing the app (settings are read at import time).
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ASSISTANT_API_KEY"] = "test-assistant-key"
os.environ["STOCKSENSE_API_URL"] = "http://stocksense-api.test"
os.environ["STOCKSENSE_API_KEY"] = "test-api-key"
os.environ["DB_PASSWORD"] = "test-password"
os.environ["GOOGLE_API_KEY"] = "test-not-a-real-key"
os.environ["LANGSMITH_TRACING"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

TEST_ASSISTANT_KEY = "test-assistant-key"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
