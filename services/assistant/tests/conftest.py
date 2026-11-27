"""Shared test setup for the assistant.

Every value is fake: tests never call Gemini, LangSmith or the real API.
From A4 on, the checkpoints are REAL: they go to the assistant's own test
database (stocksense_assistant_test) on the db-test container, so tests prove
that a paused thread really survives in Postgres.
"""

import os

TEST_DB_HOST = os.getenv("TEST_DB_HOST", "localhost")
TEST_DB_PORT = os.getenv("TEST_DB_PORT", "5433")
TEST_DB_NAME = "stocksense_assistant_test"

# Must be set BEFORE importing the app (settings are read at import time).
os.environ["APP_ENV"] = "test"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["ASSISTANT_API_KEY"] = "test-assistant-key"
os.environ["STOCKSENSE_API_URL"] = "http://stocksense-api.test"
os.environ["STOCKSENSE_API_KEY"] = "test-api-key"
os.environ["DB_HOST"] = TEST_DB_HOST
os.environ["DB_PORT"] = TEST_DB_PORT
os.environ["DB_USER"] = "stocksense"
os.environ["DB_PASSWORD"] = "test-password"
os.environ["ASSISTANT_DB_NAME"] = TEST_DB_NAME
os.environ["GOOGLE_API_KEY"] = "test-not-a-real-key"
os.environ["LANGSMITH_TRACING"] = "false"

from collections.abc import Callable, Iterator  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402
from psycopg_pool import ConnectionPool  # noqa: E402

from app.agent.assistant import Assistant  # noqa: E402
from app.agent.graph import build_graph  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import make_pool  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.threads import get_assistant  # noqa: E402
from app.tools import make_tools  # noqa: E402
from tests.fake_api import FakeApi  # noqa: E402

TEST_ASSISTANT_KEY = "test-assistant-key"
AUTH = {"X-API-Key": TEST_ASSISTANT_KEY}

# LangGraph's tables (not checkpoint_migrations: emptying it would re-run setup's migrations).
CHECKPOINT_TABLES = "checkpoints, checkpoint_blobs, checkpoint_writes"


def _create_test_database_if_missing() -> None:
    """Connect to the default 'postgres' database and create ours once."""
    admin_url = f"postgresql://stocksense:test-password@{TEST_DB_HOST}:{TEST_DB_PORT}/postgres"
    # autocommit: CREATE DATABASE can't run inside a transaction.
    with psycopg.connect(admin_url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
        if exists.fetchone() is None:
            conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


@pytest.fixture(scope="session")
def pool() -> Iterator[ConnectionPool]:
    """One pool for the whole test run, like the app's."""
    _create_test_database_if_missing()
    pool = make_pool(get_settings())
    pool.open(wait=True)
    PostgresSaver(pool).setup()
    yield pool
    pool.close()


@pytest.fixture
def clean_db(pool: ConnectionPool) -> ConnectionPool:
    """Every test starts with no saved threads."""
    with pool.connection() as conn:
        conn.execute(f"TRUNCATE {CHECKPOINT_TABLES}")
    return pool


def fake_model(*replies: AIMessage) -> GenericFakeChatModel:
    """Returns the given replies in order. It can't bind tools, so build_graph gets it as is."""
    return GenericFakeChatModel(messages=iter(replies))


def build_assistant(api: FakeApi, pool: ConnectionPool, *replies: AIMessage) -> Assistant:
    """A real graph + REAL Postgres checkpoints, with a fake model and a fake API."""
    tools = make_tools(api.client())
    graph = build_graph(fake_model(*replies), tools, PostgresSaver(pool))
    return Assistant(graph, pool)


@pytest.fixture
def make_assistant(clean_db: ConnectionPool) -> Callable[..., Assistant]:
    def make(api: FakeApi, *replies: AIMessage) -> Assistant:
        return build_assistant(api, clean_db, *replies)

    return make


@pytest.fixture
def client() -> Iterator[TestClient]:
    # No "with TestClient(...)": the lifespan (real pool, real Gemini model) does
    # NOT run. Tests that need an Assistant use api_client below instead.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def api_client(client: TestClient) -> Callable[[Assistant], TestClient]:
    """A test client whose /threads endpoints use the given Assistant."""

    def use(assistant: Assistant) -> TestClient:
        app.dependency_overrides[get_assistant] = lambda: assistant
        return client

    return use