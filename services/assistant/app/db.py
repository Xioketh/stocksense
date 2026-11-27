"""The assistant's connection pool for its OWN database (stocksense_assistant).

Only LangGraph's checkpoint tables and the thread locks live there. Business
data (products, invoices) is never read here: tools go through the API.
"""

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import Settings

# Seconds to wait for a free connection before the request fails.
POOL_TIMEOUT_SECONDS = 10


def make_pool(settings: Settings) -> ConnectionPool:
    """A pool PostgresSaver can use. Call pool.open() at startup, pool.close() at shutdown.

    The three connection settings are what PostgresSaver needs:
      autocommit=True        every checkpoint write is saved at once, no open transaction
      prepare_threshold=0    no server-side prepared statements (safe behind PgBouncer later)
      row_factory=dict_row   the saver reads columns by name
    """
    return ConnectionPool(
        conninfo=settings.assistant_db_url,
        min_size=1,
        max_size=settings.assistant_db_pool_size,
        timeout=POOL_TIMEOUT_SECONDS,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,  # opened in the app's lifespan, so import never touches the network
    )