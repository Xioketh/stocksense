"""A fake StockSense API for tests, built on httpx2.MockTransport.

No network: requests go to a Python function. Every request is recorded,
so tests can check what the agent sent (and that it sent no write).
"""

import httpx2

from app.tools.api_client import StockSenseClient

TEST_API_URL = "http://stocksense-api.test"
TEST_API_KEY = "test-api-key"


def product(sku: str, name: str, qty: int, threshold: int) -> dict:
    """A product exactly as the API returns it (ProductOut)."""
    return {
        "id": 1,
        "sku": sku,
        "name": name,
        "qty": qty,
        "low_stock_threshold": threshold,
        "is_low_stock": qty <= threshold,
        "created_at": "2026-11-20T10:00:00Z",
    }


class FakeApi:
    def __init__(self, routes: dict[tuple[str, str], object] | None = None) -> None:
        # (method, path) -> (status, json body), or an exception to raise
        self.routes = routes or {}
        self.requests: list[httpx2.Request] = []

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        answer = self.routes.get((request.method, request.url.path))
        if answer is None:
            return httpx2.Response(404, json={"detail": "Not Found"})
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx2.Response(status, json=body)

    def client(self) -> StockSenseClient:
        return StockSenseClient(
            base_url=TEST_API_URL,
            api_key=TEST_API_KEY,
            timeout_seconds=5,
            transport=httpx2.MockTransport(self._handle),
        )

    def methods(self) -> list[str]:
        return [r.method for r in self.requests]