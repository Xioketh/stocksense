from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    """Liveness: is the process running? No database call."""
    return {"status": "ok"}
