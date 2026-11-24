import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.events import get_event_publisher
from app.logging_config import setup_logging
from app.routers import health, invoices, products, stock
from app.storage import get_upload_signer

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once when the container starts, before it accepts any request.

    Same idea as the worker: build the Google Cloud clients NOW, so a
    misconfigured revision (e.g. EVENTS_BACKEND=fake on Cloud Run) crashes
    at startup. Cloud Run then keeps serving the previous, working revision.
    (The migration job uses this image too, but it runs alembic, not uvicorn,
    so it never runs this code.)
    """
    get_upload_signer()
    get_event_publisher()
    logger.info(
        "app started",
        extra={
            "app_env": settings.app_env,
            "storage_backend": settings.storage_backend,
            "events_backend": settings.events_backend,
        },
    )
    yield


app = FastAPI(
    title="StockSense API",
    version="0.3.0",
    description="AI-assisted inventory for small shops.",
    lifespan=lifespan,
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(products.router)
app.include_router(stock.router)
app.include_router(invoices.router)
