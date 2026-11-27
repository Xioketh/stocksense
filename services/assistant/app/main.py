import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres import PostgresSaver

from app.agent.assistant import Assistant
from app.agent.graph import build_graph
from app.agent.model import make_chat_model
from app.config import get_settings
from app.db import make_pool
from app.errors import AssistantError
from app.logging_config import setup_logging
from app.routers import health, threads
from app.tools import make_tools
from app.tools.api_client import StockSenseClient

# get_settings() at import time: a missing required variable (e.g. GOOGLE_API_KEY)
# crashes the container at startup with a clear error, not on the first request.
settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: open the pool, create the checkpoint tables, build the graph ONCE.

    Shutdown: close the API client and the pool. The graph itself holds no
    conversation data; every thread lives in Postgres.
    """
    pool = make_pool(settings)
    pool.open(wait=True)  # fail at startup if the database is unreachable
    checkpointer = PostgresSaver(pool)
    # Creates/upgrades LangGraph's own tables (checkpoints, checkpoint_blobs,
    # checkpoint_writes, checkpoint_migrations). Safe to run on every start.
    checkpointer.setup()

    client = StockSenseClient.from_settings(settings)
    tools = make_tools(client)
    graph = build_graph(make_chat_model(settings, tools.all), tools, checkpointer)
    app.state.assistant = Assistant(graph, pool)

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
    try:
        yield
    finally:
        client.close()
        pool.close()


app = FastAPI(
    title="StockSense Assistant",
    version="0.2.0",
    description="An AI agent that answers stock questions and proposes changes for approval.",
    lifespan=lifespan,
)


@app.exception_handler(AssistantError)
def assistant_error(request: Request, exc: AssistantError) -> JSONResponse:
    """Every expected error becomes {"detail": "..."} with its status (same shape as the API)."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health.router)
app.include_router(threads.router)