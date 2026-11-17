import logging

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.logging_config import setup_logging
from app.routers import health, products, stock

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="StockSense API",
    version="0.1.0",
    description="AI-assisted inventory for small shops.",
)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(products.router)
app.include_router(stock.router)

logger.info("app started", extra={"app_env": settings.app_env})