import json

from app.tools import make_tools
from tests.fake_api import FakeApi, product


def tools_for(api: FakeApi) -> dict:
    return {t.name: t for t in make_tools(api.client()).all}


def test_list_low_stock_asks_for_the_filter_and_returns_compact_json():
    body = {"items": [product("RICE-5", "Rice 5kg", 2, 5)], "total": 1, "limit": 50, "offset": 0}
    api = FakeApi({("GET", "/products"): (200, body)})

    result = json.loads(tools_for(api)["list_low_stock"].invoke({}))

    assert api.requests[0].url.params["low_stock"] == "true"
    assert result == {
        "items": [{"sku": "RICE-5", "name": "Rice 5kg", "qty": 2, "threshold": 5}],
        "total": 1,
        "shown": 1,
    }


def test_get_product_upper_cases_the_sku():
    api = FakeApi({("GET", "/products/RICE-5"): (200, product("RICE-5", "Rice 5kg", 20, 5))})

    result = json.loads(tools_for(api)["get_product"].invoke({"sku": " rice-5 "}))

    assert result["qty"] == 20
    assert result["is_low_stock"] is False


def test_get_product_refuses_a_bad_sku_without_calling_the_api():
    api = FakeApi()

    result = json.loads(tools_for(api)["get_product"].invoke({"sku": "../invoices"}))

    assert result["error"] == "invalid_request"
    assert api.requests == []


def test_get_product_not_found_is_an_error_result_not_an_exception():
    api = FakeApi({("GET", "/products/NOPE"): (404, {"detail": "Product 'NOPE' not found"})})

    result = json.loads(tools_for(api)["get_product"].invoke({"sku": "NOPE"}))

    assert result == {
        "error": "not_found",
        "status_code": 404,
        "reason": "Product 'NOPE' not found",
    }


def test_get_invoice_keeps_only_what_the_agent_needs():
    body = {
        "id": 12,
        "status": "processed",
        "original_filename": "inv.pdf",
        "content_type": "application/pdf",
        "error_message": None,
        "attempts": 1,
        "created_at": "2026-11-20T10:00:00Z",
        "uploaded_at": None,
        "processed_at": None,
        "items": [
            {
                "id": 99,
                "line_no": 2,
                "raw_sku": None,
                "raw_name": "Basmathi Rice 5kg",
                "qty": 10,
                "matched_product_id": None,
                "status": "needs_review",
            }
        ],
    }
    api = FakeApi({("GET", "/invoices/12"): (200, body)})

    result = json.loads(tools_for(api)["get_invoice"].invoke({"invoice_id": 12}))

    assert result["lines"] == [
        {
            "line_no": 2,
            "raw_sku": None,
            "raw_name": "Basmathi Rice 5kg",
            "qty": 10,
            "status": "needs_review",
        }
    ]
    assert "matched_product_id" not in result["lines"][0]


def test_resolve_posts_the_sku_and_trims_the_response():
    body = {"invoice_id": 12, "line_no": 2, "sku": "RICE-5", "added": 10, "new_qty": 30}
    api = FakeApi({("POST", "/invoices/12/items/2/resolve"): (200, body)})

    result = json.loads(
        tools_for(api)["resolve_review_item"].invoke(
            {"invoice_id": 12, "line_no": 2, "sku": "rice-5"}
        )
    )

    assert json.loads(api.requests[0].content) == {"sku": "RICE-5"}
    assert result == {"sku": "RICE-5", "added": 10, "new_qty": 30}


def test_resolve_conflict_is_reported():
    api = FakeApi(
        {("POST", "/invoices/12/items/2/resolve"): (409, {"detail": "Line 2 is already matched"})}
    )

    result = json.loads(
        tools_for(api)["resolve_review_item"].invoke(
            {"invoice_id": 12, "line_no": 2, "sku": "RICE-5"}
        )
    )

    assert result["error"] == "conflict"
    assert result["status_code"] == 409