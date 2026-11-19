from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All app settings, read from environment variables (or a .env file).

    The same code runs locally, in Docker and on Cloud Run;
    only the environment variables change.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unrelated variables in .env (e.g. POSTGRES_*)
    )

    app_name: str = "stocksense-api"
    app_env: str = "local"  # local | dev | prod
    log_level: str = "INFO"

    # Database: separate parts instead of one URL, because on Cloud Run
    # the password will come from Secret Manager as its own variable.
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "stocksense"
    db_user: str = "stocksense"
    db_password: SecretStr

    # API key that clients send in the X-API-Key header.
    api_key: SecretStr

    # Invoice uploads (Cloud Storage signed URLs).
    # "fake" = no Google Cloud needed (local dev + tests); "gcs" = real signed URLs.
    # These have defaults on purpose: the migration job uses the same image and
    # settings, and it must keep working without any storage variables.
    storage_backend: Literal["gcs", "fake"] = "fake"
    invoices_bucket: str = ""
    upload_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)  # 15 minutes
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1)  # 10 MB

    @property
    def database_url(self) -> str:
        password = self.db_password.get_secret_value()
        return (
            f"postgresql+psycopg://{self.db_user}:{password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Create the Settings object once and reuse it."""
    return Settings()