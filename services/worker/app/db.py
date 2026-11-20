from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # check a connection is alive before using it
    pool_size=2,  # the worker handles few requests at a time
    max_overflow=2,
    # Fail fast (5 s) if Cloud SQL is stopped or unreachable, instead of hanging.
    # The request then returns 503 and Pub/Sub retries it later.
    connect_args={"connect_timeout": 5},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Parent class for the worker's ORM models."""


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
