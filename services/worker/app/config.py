from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Worker settings, read from environment variables (or a .env file).

    Same idea as the API: one image, different environment per place it runs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also has API-only variables
    )

    app_name: str = "stocksense-worker"
    app_env: str = "local"  # local | dev | prod
    log_level: str = "INFO"

    # Same database as the API (shared on purpose, see the brief).
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "stocksense"
    db_user: str = "stocksense"
    db_password: SecretStr

    # The only bucket we accept events from. Required: a worker that
    # doesn't know its bucket is misconfigured, so it should not start.
    invoices_bucket: str = Field(min_length=1)
    # "fake" = no Google Cloud (local dev + tests); "gcs" = read the real bucket.
    # Same name and values as the API's STORAGE_BACKEND.
    storage_backend: Literal["gcs", "fake"] = "fake"
    # Must match the API's MAX_UPLOAD_BYTES (the signed URL's size limit).
    max_invoice_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    # How long a claimed invoice belongs to one worker. MUST be longer than the
    # Cloud Run request timeout (300 s): once a lease is older than this, the
    # request that took it has certainly been stopped, so another may take over.
    processing_lease_seconds: int = Field(default=600, ge=301)

    # ---------- Invoice extraction (Gemini on Vertex AI) ----------
    # "fake" = a canned answer, no Google Cloud (local dev + tests).
    # "gemini" = the real model. Defaults keep today's deploys working:
    # nothing calls the extractor until the processing step is wired in.
    extractor_backend: Literal["gemini", "fake"] = "fake"
    # The project that is billed for Gemini calls. Required for "gemini".
    # (Cloud Run does NOT set this automatically, so we set it ourselves.)
    google_cloud_project: str = ""
    # "global": current Gemini models aren't offered pay-as-you-go in asia-south1.
    gemini_location: str = "global"
    gemini_model: str = "gemini-3.5-flash"
    # Reading an invoice needs little reasoning; less thinking = cheaper + faster.
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = "low"
    # Time budget per call x attempts must stay well under the 300 s ack deadline:
    # 45 s x 3 attempts + backoff waits ~= 150 s at worst.
    gemini_timeout_seconds: int = Field(default=45, ge=5, le=120)
    gemini_max_attempts: int = Field(default=3, ge=1, le=5)

    # ---------- Invoice extraction (Gemini on Vertex AI) ----------
    # "fake" = a canned answer, no Google Cloud (local dev + tests).
    # "gemini" = the real model. Defaults keep today's deploys working:
    # nothing calls the extractor until the processing step is wired in.
    extractor_backend: Literal["gemini", "fake"] = "fake"
    # The project that is billed for Gemini calls. Required for "gemini".
    # (Cloud Run does NOT set this automatically, so we set it ourselves.)
    google_cloud_project: str = ""
    # "global": current Gemini models aren't offered pay-as-you-go in asia-south1.
    gemini_location: str = "global"
    gemini_model: str = "gemini-3.5-flash"
    # Reading an invoice needs little reasoning; less thinking = cheaper + faster.
    gemini_thinking_level: Literal["minimal", "low", "medium", "high"] = "low"
    # Time budget per call x attempts must stay well under the 300 s ack deadline:
    # 45 s x 3 attempts + backoff waits ~= 150 s at worst.
    gemini_timeout_seconds: int = Field(default=45, ge=5, le=120)
    gemini_max_attempts: int = Field(default=3, ge=1, le=5)

    @property
    def database_url(self) -> str:
        password = self.db_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
