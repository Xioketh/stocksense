from functools import lru_cache

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
