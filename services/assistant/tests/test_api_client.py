import httpx2
import pytest

from app.tools.api_client import ApiError
from tests.fake_api import TEST_API_KEY, FakeApi


def test_sends_the_api_key_and_returns_json():
    api = FakeApi({("GET", "/products/RICE-5"): (200, {"sku": "RICE-5"})})

    assert api.client().get("/products/RICE-5") == {"sku": "RICE-5"}
    assert api.requests[0].headers["X-API-Key"] == TEST_API_KEY


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, "not_found"), (409, "conflict"), (401, "unauthorized"), (500, "api_error")],
)
def test_http_errors_become_one_shape(status, error):
    api = FakeApi({("GET", "/x"): (status, {"detail": "something happened"})})

    with pytest.raises(ApiError) as exc_info:
        api.client().get("/x")

    assert exc_info.value.error == error
    assert exc_info.value.status_code == status
    assert exc_info.value.reason == "something happened"


def test_validation_details_are_shortened():
    detail = [{"msg": "field required"}, {"msg": "not an int"}]
    api = FakeApi({("POST", "/x"): (422, {"detail": detail})})

    with pytest.raises(ApiError) as exc_info:
        api.client().post("/x", body={})

    assert exc_info.value.error == "invalid_request"
    assert exc_info.value.reason == "field required; not an int"


@pytest.mark.parametrize(
    "exc", [httpx2.ReadTimeout("timed out"), httpx2.ConnectError("connection refused")]
)
def test_timeouts_and_connection_errors_are_api_unavailable(exc):
    api = FakeApi({("GET", "/x"): exc})

    with pytest.raises(ApiError) as exc_info:
        api.client().get("/x")

    assert exc_info.value.error == "api_unavailable"
    assert exc_info.value.status_code is None