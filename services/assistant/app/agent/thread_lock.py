"""One run per thread at a time, across every container.

Without this, a double-clicked "Approve" resumes the same checkpoint twice:
both runs execute write_tools. The API's 409 and the UNIQUE constraint still
protect stock, but the thread's history would fork. A Postgres advisory lock
is shared by every assistant instance (they all use the same database), so it
still works when Cloud Run runs several copies in Phase E.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from app.errors import ThreadBusy

# hashtextextended() turns the thread id into the 64-bit number advisory locks use.
_TRY_LOCK = "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked"
_UNLOCK = "SELECT pg_advisory_unlock(hashtextextended(%s, 0))"


@contextmanager
def thread_lock(pool: ConnectionPool, thread_id: str) -> Iterator[None]:
    """Hold the thread's lock for the whole run, or raise ThreadBusy at once (no waiting).

    A session lock belongs to the connection, so the same connection is kept
    until the unlock. If the process dies, Postgres closes the connection and
    the lock is released by itself: a crash can never leave a thread locked.
    """
    with pool.connection() as conn:
        row = conn.execute(_TRY_LOCK, (thread_id,)).fetchone()
        if not row["locked"]:
            raise ThreadBusy()
        try:
            yield
        finally:
            conn.execute(_UNLOCK, (thread_id,))
