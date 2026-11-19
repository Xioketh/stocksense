import secrets

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import Settings, get_settings

# Tells FastAPI to read the "X-API-Key" header. It also adds an
# "Authorize" button to the /docs page so you can test easily.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.api_key.get_secret_value()
    # compare_digest takes the same time whether the first or the last
    # character is wrong, so attackers can't guess the key by timing.
    if api_key is None or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
