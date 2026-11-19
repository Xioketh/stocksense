from functools import lru_cache

from pydantic import SecretStr
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
