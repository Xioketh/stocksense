"""API tests for /products, using a real test database."""


def test_create_product_returns_201(client):
    response = client.post(
        "/products",
        json={"sku": "SUGAR-1", "name": "Sugar 1kg", "qty": 30, "low_stock_threshold": 10},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "SUGAR-1"
    assert body["qty"] == 30
    assert body["is_low_stock"] is False
    assert "id" in body


def test_created_product_appears_in_list(client, rice):
    response = client.get("/products")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [p["sku"] for p in body["items"]] == ["RICE-5"]


def test_duplicate_sku_returns_409(client, rice):
    response = client.post("/products", json={"sku": "RICE-5", "name": "Another rice"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_invalid_product_returns_422(client):
    # negative qty and lowercase SKU both break the Pydantic rules
    response = client.post("/products", json={"sku": "rice", "name": "Rice", "qty": -1})

    assert response.status_code == 422


def test_get_unknown_product_returns_404(client):
    response = client.get("/products/NOPE-1")

    assert response.status_code == 404


def test_pagination_limit_and_offset(client):
    for i in range(3):
        client.post("/products", json={"sku": f"ITEM-{i}", "name": f"Item {i}"})

    response = client.get("/products", params={"limit": 2, "offset": 1})

    body = response.json()
    assert body["total"] == 3
    assert [p["sku"] for p in body["items"]] == ["ITEM-1", "ITEM-2"]


def test_missing_api_key_returns_401(anon_client):
    response = anon_client.get("/products")

    assert response.status_code == 401


def test_health_does_not_need_api_key(anon_client):
    response = anon_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}