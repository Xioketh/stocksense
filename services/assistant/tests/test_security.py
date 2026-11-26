"""require_api_key is tested on a tiny app of its own: A2 has no protected
routes yet. From A4, /threads/* use the same dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.security import require_api_key
from tests.conftest import TEST_ASSISTANT_KEY


@pytest.fixture
def protected_client() -> TestClient:
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected() -> dict:
        return {"ok": True}

    return TestClient(app)


def test_correct_key_is_accepted(protected_client):
    response = protected_client.get("/protected", headers={"X-API-Key": TEST_ASSISTANT_KEY})
    assert response.status_code == 200


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key"}])
def test_missing_or_wrong_key_is_rejected(protected_client, headers):
    response = protected_client.get("/protected", headers=headers)
    assert response.status_code == 401


def test_api_key_is_not_accepted(protected_client):
    """The StockSense API key must not unlock the assistant (separate keys)."""
    response = protected_client.get("/protected", headers={"X-API-Key": "test-api-key"})
    assert response.status_code == 401
