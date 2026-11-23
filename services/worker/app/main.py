import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.extraction import get_extractor
from app.logging_config import setup_logging
from app.routers import health, pubsub
from app.storage import get_invoice_files

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Runs once when the container starts, before it accepts any request.

    Build the file reader and the extractor NOW, so a misconfigured revision
    (e.g. EXTRACTOR_BACKEND=fake on Cloud Run, or GOOGLE_CLOUD_PROJECT missing)
    crashes at startup. Cloud Run then never sends it traffic and keeps the
    previous, working revision - instead of every message failing later.
    """
    get_invoice_files()
    get_extractor()
    logger.info(
        "worker started",
        extra={
            "app_env": settings.app_env,
            "bucket": settings.invoices_bucket,
            "storage_backend": settings.storage_backend,
            "extractor_backend": settings.extractor_backend,
        },
    )
    yield


app = FastAPI(
    title="StockSense Worker",
    version="0.2.0",
    description="Receives Pub/Sub push messages about uploaded invoices and processes them.",
    lifespan=lifespan,
)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    """Database down or unreachable: a TEMPORARY problem.

    503 tells Pub/Sub "not done", so it redelivers the message later
    (with backoff). Nothing is lost while Cloud SQL is stopped.
    """
    logger.error("database unavailable", extra={"path": request.url.path})
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


app.include_router(health.router)
app.include_router(pubsub.router)