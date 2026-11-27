"""The /threads endpoints over HTTP: auth, status codes and response shapes.

The flow logic is tested in test_assistant.py; here we check the HTTP layer.
"""

from langchain_core.messages import AIMessage

from tests.conftest import AUTH
from tests.fake_api import FakeApi

THREAD = "22222222-2222-2222-2222-222222222222"
RESOLVE_PATH = "/invoices/12/items/2/resolve"
PROPOSAL = AIMessage(
    content="",
    tool_calls=[
        {
            "name": "resolve_review_item",
            "args": {"invoice_id": 12, "line_no": 2, "sku": "RICE-5"},
            "id": "w1",
            "type": "tool_call",
        }
    ],
)
RESOLVED = (200, {"invoice_id": 12, "line_no": 2, "sku": "RICE-10", "added": 10, "new_qty": 30})


def test_every_threads_endpoint_needs_the_key(client):
    assert client.post("/threads").status_code == 401
    assert client.get(f"/threads/{THREAD}").status_code == 401
    assert client.post(f"/threads/{THREAD}/messages", json={"text": "hi"}).status_code == 401


def test_create_thread_returns_a_new_id(client):
    first = client.post("/threads", headers=AUTH)
    second = client.post("/threads", headers=AUTH)

    assert first.status_code == 201
    assert first.json()["thread_id"] != second.json()["thread_id"]


def test_a_thread_id_must_be_a_uuid(api_client, make_assistant):
    client = api_client(make_assistant(FakeApi()))

    assert client.get("/threads/not-a-uuid", headers=AUTH).status_code == 422


def test_unknown_thread_is_404(api_client, make_assistant):
    client = api_client(make_assistant(FakeApi()))

    response = client.get(f"/threads/{THREAD}", headers=AUTH)

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_empty_message_is_422(api_client, make_assistant):
    client = api_client(make_assistant(FakeApi()))

    response = client.post(f"/threads/{THREAD}/messages", json={"text": ""}, headers=AUTH)

    assert response.status_code == 422


def test_answered_turn_shape(api_client, make_assistant):
    client = api_client(make_assistant(FakeApi(), AIMessage(content="Hello!")))

    response = client.post(f"/threads/{THREAD}/messages", json={"text": "Hi"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": THREAD,
        "status": "answered",
        "answer": "Hello!",
        "proposals": [],
    }


def test_pending_then_409_then_edit_and_approve(api_client, make_assistant):
    api = FakeApi({("POST", RESOLVE_PATH): RESOLVED})
    client = api_client(make_assistant(api, PROPOSAL, AIMessage(content="Done.")))
    url = f"/threads/{THREAD}"

    pending = client.post(f"{url}/messages", json={"text": "Line 2 is rice"}, headers=AUTH)
    assert pending.json()["status"] == "pending_approval"
    assert pending.json()["proposals"][0]["id"] == "w1"

    blocked = client.post(f"{url}/messages", json={"text": "and sugar?"}, headers=AUTH)
    assert blocked.status_code == 409
    assert "waiting for approval" in blocked.json()["detail"]

    edits = {"edits": [{"tool_call_id": "w1", "args": {"sku": "RICE-10"}}]}
    approved = client.post(f"{url}/approve", json=edits, headers=AUTH)
    assert approved.status_code == 200
    assert approved.json()["answer"] == "Done."

    again = client.post(f"{url}/approve", headers=AUTH)
    assert again.status_code == 409


def test_bad_edit_id_is_400(api_client, make_assistant):
    client = api_client(make_assistant(FakeApi(), PROPOSAL))
    client.post(f"/threads/{THREAD}/messages", json={"text": "Line 2 is rice"}, headers=AUTH)

    edits = {"edits": [{"tool_call_id": "nope", "args": {"sku": "RICE-10"}}]}
    response = client.post(f"/threads/{THREAD}/approve", json=edits, headers=AUTH)

    assert response.status_code == 400


def test_reject_without_a_body(api_client, make_assistant):
    api = FakeApi()
    client = api_client(make_assistant(api, PROPOSAL, AIMessage(content="Left it as is.")))
    client.post(f"/threads/{THREAD}/messages", json={"text": "Line 2 is rice"}, headers=AUTH)

    response = client.post(f"/threads/{THREAD}/reject", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["answer"] == "Left it as is."
    assert api.requests == []


def test_get_thread_shows_the_history(api_client, make_assistant):
    client = api_client(make_assistant(FakeApi(), PROPOSAL))
    client.post(f"/threads/{THREAD}/messages", json={"text": "Line 2 is rice"}, headers=AUTH)

    body = client.get(f"/threads/{THREAD}", headers=AUTH).json()

    assert body["status"] == "pending_approval"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][1]["tool_calls"][0]["tool"] == "resolve_review_item"