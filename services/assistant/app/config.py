from functools import lru_cache
from typing import Self
from urllib.parse import quote

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Assistant settings, read from environment variables (or a .env file).

    Same idea as the api and worker: one image, different environment per place it runs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also has api/worker-only variables
    )

    app_name: str = "stocksense-assistant"
    app_env: str = "local"  # local | dev | prod
    log_level: str = "INFO"

    # ---------- Who may call the assistant ----------
    # Clients send this in X-API-Key. A DIFFERENT key from the API's on purpose:
    # leaking one doesn't open the other.
    assistant_api_key: SecretStr

    # ---------- How the assistant reaches StockSense ----------
    # Tools call the API over HTTP; they never touch business tables directly.
    stocksense_api_url: str = "http://localhost:8000"
    stocksense_api_key: SecretStr
    stocksense_api_timeout_seconds: float = Field(default=10, gt=0, le=30)

    # ---------- The assistant's OWN database (checkpoints, embeddings) ----------
    # Same Postgres server and user as the API, different database.
    # NOT db_name: in the shared .env, DB_NAME is the API's database.
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "stocksense"
    db_password: SecretStr
    assistant_db_name: str = "stocksense_assistant"
    # Connections shared by all requests. One chat run can use 2 at once
    # (the thread lock holds one, the checkpointer borrows another).
    assistant_db_pool_size: int = Field(default=10, ge=2, le=50)

    # ---------- Gemini (AI Studio key locally; Vertex AI in Phase E) ----------
    google_api_key: SecretStr
    gemini_model: str = "gemini-3.5-flash"

    # ---------- LangSmith tracing (read by the LangSmith SDK from env vars) ----------
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "stocksense-assistant"

    @model_validator(mode="after")
    def tracing_needs_a_key(self) -> Self:
        # Fail at startup, not on the first traced request.
        if self.langsmith_tracing and self.langsmith_api_key is None:
            raise ValueError("LANGSMITH_TRACING=true needs LANGSMITH_API_KEY")
        return self

    @property
    def assistant_db_url(self) -> str:
        """psycopg connection string (PostgresSaver uses psycopg, not SQLAlchemy)."""
        password = quote(self.db_password.get_secret_value(), safe="")
        return (
            f"postgresql://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.assistant_db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()