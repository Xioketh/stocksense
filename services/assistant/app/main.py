import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.logging_config import setup_logging
from app.routers import health

# get_settings() at import time: a missing required variable (e.g. GOOGLE_API_KEY)
# crashes the container at startup with a clear error, not on the first request.
settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once at startup. A4 adds the Postgres checkpointer here."""
    logger.info(
        "assistant started",
        extra={
            "app_env": settings.app_env,
            "stocksense_api_url": settings.stocksense_api_url,
            "assistant_db": settings.assistant_db_name,
            "gemini_model": settings.gemini_model,
            "langsmith_tracing": settings.langsmith_tracing,
        },
    )
    yield


app = FastAPI(
    title="StockSense Assistant",
    version="0.1.0",
    description="An AI agent that answers stock questions and proposes changes for approval.",
    lifespan=lifespan,
)

app.include_router(health.router)
