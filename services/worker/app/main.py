import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.logging_config import setup_logging
from app.routers import health, pubsub

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="StockSense Worker",
    version="0.1.0",
    description="Receives Pub/Sub push messages about uploaded invoices.",
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

logger.info(
    "worker started",
    extra={"app_env": settings.app_env, "bucket": settings.invoices_bucket},
)
