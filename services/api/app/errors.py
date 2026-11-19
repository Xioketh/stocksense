from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    """Something the client asked for doesn't exist -> 404."""


class ConflictError(Exception):
    """The request clashes with the current state (duplicate SKU, not enough stock) -> 409."""


def register_error_handlers(app: FastAPI) -> None:
    """Turn our own exceptions into clean JSON HTTP responses."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})
