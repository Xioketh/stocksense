import pytest
from pydantic import ValidationError

from app.config import Settings


def test_tracing_without_key_fails_at_startup(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="LANGSMITH_API_KEY"):
        Settings(_env_file=None)


def test_assistant_db_url_uses_its_own_database_and_escapes_the_password(monkeypatch):
    monkeypatch.setenv("DB_NAME", "stocksense")  # the API's database, from the shared .env
    monkeypatch.setenv("DB_PASSWORD", "p@ss/word")
    monkeypatch.delenv("ASSISTANT_DB_NAME", raising=False)  # conftest points it at the test db

    url = Settings(_env_file=None).assistant_db_url

    assert url.endswith("/stocksense_assistant")
    assert "p%40ss%2Fword" in url
