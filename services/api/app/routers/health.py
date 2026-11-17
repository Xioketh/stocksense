import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    """Liveness: is the app process running? Fast, no database call."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> JSONResponse:
    """Readiness: can the app reach the database?"""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("database not reachable")
        return JSONResponse(status_code=503, content={"status": "error", "database": "down"})
    return JSONResponse(status_code=200, content={"status": "ok", "database": "up"})