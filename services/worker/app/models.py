
"""The worker's view of the shared database.

The API OWNS the schema: its Alembic migrations create and change these
tables. Here we map only the columns the worker reads or writes, so the
worker never runs migrations and can't accidentally change the schema.
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    gcs_path: Mapped[str] = mapped_column(String(300), unique=True)
    status: Mapped[str] = mapped_column(String(20))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))