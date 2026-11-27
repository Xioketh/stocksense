"""A small HTTP client for the StockSense API.

The tools never talk to the database. They call the API, so the API's
validation, row locks, stock_movements audit rows and events apply to
agent actions exactly as they do to a person using /docs.
"""

import json
import logging
from typing import Any

import httpx2

from app.config import Settings

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Any failed API call, in ONE shape the tools can hand to the LLM.

    error:       a short machine word (not_found, conflict, ...)
    status_code: the HTTP status, or None when the API was never reached
    reason:      a human sentence (the API's "detail" when it sent one)
    """

    def __init__(self, error: str, status_code: int | None, reason: str) -> None:
        super().__init__(reason)
        self.error = error
        self.status_code = status_code
        self.reason = reason

    def to_json(self) -> str:
        return json.dumps(
            {"error": self.error, "status_code": self.status_code, "reason": self.reason}
        )


# Status codes the LLM can do something useful with get their own word.
_ERROR_WORDS = {
    400: "invalid_request",
    401: "unauthorized",
    404: "not_found",
    409: "conflict",
    422: "invalid_request",
}


class StockSenseClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        transport: httpx2.BaseTransport | None = None,  # tests pass a MockTransport
    ) -> None:
        self._http = httpx2.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=httpx2.Timeout(timeout_seconds),
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "StockSenseClient":
        return cls(
            base_url=settings.stocksense_api_url,
            api_key=settings.stocksense_api_key.get_secret_value(),
            timeout_seconds=settings.stocksense_api_timeout_seconds,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict[str, Any]) -> dict:
        return self._request("POST", path, json=body)

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx2.TimeoutException as exc:
            logger.warning("stocksense api timeout", extra={"method": method, "path": path})
            raise ApiError("api_unavailable", None, "The StockSense API timed out.") from exc
        except httpx2.TransportError as exc:  # connection refused, DNS, ...
            logger.warning("stocksense api unreachable", extra={"method": method, "path": path})
            raise ApiError("api_unavailable", None, "The StockSense API is unreachable.") from exc

        if response.is_success:
            return response.json()

        reason = _detail(response)
        status = response.status_code
        # 401 means OUR configuration is wrong (STOCKSENSE_API_KEY), not the user's question.
        log = logger.error if status == 401 or status >= 500 else logger.info
        log(
            "stocksense api error",
            extra={"method": method, "path": path, "status_code": status, "reason": reason},
        )
        raise ApiError(_ERROR_WORDS.get(status, "api_error"), status, reason)


def _detail(response: httpx2.Response) -> str:
    """The API sends {"detail": "..."}; fall back to the status text."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    # 422 details are a list of validation errors; keep them short for the LLM.
    if isinstance(detail, list):
        detail = "; ".join(str(d.get("msg", d)) for d in detail[:3])
    return str(detail) if detail else response.reason_phrase or f"HTTP {response.status_code}"
