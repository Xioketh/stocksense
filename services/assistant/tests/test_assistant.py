"""The approval flow against REAL Postgres checkpoints (fake model, fake API)."""

import json

import pytest
from langchain_core.messages import AIMessage

from app.agent.thread_lock import thread_lock
from app.config import get_settings
from app.db import make_pool
from app.errors import (
    AgentGaveUp,
    ApprovalPending,
    InvalidEdit,
    NothingToApprove,
    ThreadBusy,
    ThreadNotFound,
)
from tests.conftest import build_assistant
from tests.fake_api import FakeApi, product

THREAD = "11111111-1111-1111-1111-111111111111"
RESOLVE_PATH = "/invoices/12/items/2/resolve"


def call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def propose_resolve(sku: str = "RICE-5", call_id: str = "w1") -> AIMessage:
    """What Gemini sends when it wants to resolve line 2 of invoice 12.

    additional_kwargs stands in for Gemini's thought signatures: an edit must keep them.
    """
    return AIMessage(
        content="",
        tool_calls=[
            call("resolve_review_item", {"invoice_id": 12, "line_no": 2, "sku": sku}, call_id)
        ],
        additional_kwargs={"signatures": "keep-me"},
    )


def resolved(sku: str = "RICE-5") -> tuple[int, dict]:
    return 200, {"invoice_id": 12, "line_no": 2, "sku": sku, "added": 10, "new_qty": 30}


def posts(api: FakeApi) -> list[dict]:
    return [json.loads(r.content) for r in api.requests if r.method == "POST"]


# ---------- questions ----------


def test_a_question_is_answered_and_saved(make_assistant):
    api = FakeApi({("GET", "/products/RICE-5"): (200, product("RICE-5", "Rice 5kg", 20, 5))})
    assistant = make_assistant(
        api,
        AIMessage(content="", tool_calls=[call("get_product", {"sku": "RICE-5"}, "r1")]),
        AIMessage(content="Rice 5kg: 20."),
    )

    turn = assistant.send_message(THREAD, "How much rice?")

    assert turn.status == "answered"
    assert turn.answer == "Rice 5kg: 20."
    saved = assistant.get_thread(THREAD)
    assert [m.type for m in saved.messages] == ["human", "ai", "tool", "ai"]


def test_unknown_thread_is_404(make_assistant):
    assistant = make_assistant(FakeApi())

    with pytest.raises(ThreadNotFound):
        assistant.get_thread(THREAD)
    with pytest.raises(ThreadNotFound):
        assistant.approve(THREAD)


# ---------- the pause ----------


def test_a_write_pauses_and_nothing_is_posted(make_assistant):
    api = FakeApi()
    assistant = make_assistant(api, propose_resolve())

    turn = assistant.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")

    assert turn.status == "pending_approval"
    assert turn.proposals == [
        {
            "id": "w1",
            "tool": "resolve_review_item",
            "args": {"invoice_id": 12, "line_no": 2, "sku": "RICE-5"},
        }
    ]
    assert api.requests == []


def test_a_new_message_while_paused_is_refused(make_assistant):
    assistant = make_assistant(FakeApi(), propose_resolve())
    assistant.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")

    with pytest.raises(ApprovalPending):
        assistant.send_message(THREAD, "Actually, what's running low?")


def test_approve_without_a_pending_change_is_refused(make_assistant):
    assistant = make_assistant(FakeApi(), AIMessage(content="Hello!"))
    assistant.send_message(THREAD, "Hi")

    with pytest.raises(NothingToApprove):
        assistant.approve(THREAD)
    with pytest.raises(NothingToApprove):
        assistant.reject(THREAD)


# ---------- approve ----------


def test_approve_runs_the_write_once(make_assistant):
    api = FakeApi({("POST", RESOLVE_PATH): resolved()})
    assistant = make_assistant(
        api, propose_resolve(), AIMessage(content="Done: Rice 5kg is now 30.")
    )
    assistant.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")

    turn = assistant.approve(THREAD)

    assert turn.status == "answered"
    assert turn.answer == "Done: Rice 5kg is now 30."
    assert posts(api) == [{"sku": "RICE-5"}]
    with pytest.raises(NothingToApprove):  # a second approve can't run it again
        assistant.approve(THREAD)
    assert len(posts(api)) == 1


def test_approve_with_an_edit_posts_the_edited_args(make_assistant):
    api = FakeApi({("POST", RESOLVE_PATH): resolved("RICE-10")})
    assistant = make_assistant(api, propose_resolve(), AIMessage(content="Done."))
    assistant.send_message(THREAD, "Line 2 of invoice 12 is rice")

    assistant.approve(THREAD, edits={"w1": {"sku": "RICE-10"}})

    assert posts(api) == [{"sku": "RICE-10"}]
    messages = assistant.get_thread(THREAD).messages
    # REPLACED, not appended: still one proposal, now with the new SKU and the old signatures.
    assert [m.type for m in messages] == ["human", "ai", "tool", "ai"]
    assert messages[1].tool_calls[0]["args"]["sku"] == "RICE-10"
    assert messages[1].tool_calls[0]["args"]["invoice_id"] == 12  # untouched args stay
    assert messages[1].additional_kwargs == {"signatures": "keep-me"}


def test_an_edit_for_an_unknown_call_is_refused_and_nothing_runs(make_assistant):
    api = FakeApi()
    assistant = make_assistant(api, propose_resolve())
    assistant.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")

    with pytest.raises(InvalidEdit, match="w1"):
        assistant.approve(THREAD, edits={"nope": {"sku": "RICE-10"}})

    assert api.requests == []
    assert assistant.get_thread(THREAD).status == "pending_approval"  # still waiting


def test_a_stale_approval_becomes_a_polite_reply(make_assistant):
    """Someone resolved the line in /docs while the proposal waited: the API says 409."""
    api = FakeApi({("POST", RESOLVE_PATH): (409, {"detail": "Invoice line 2 is not needs_review"})})
    assistant = make_assistant(
        api, propose_resolve(), AIMessage(content="That line was already resolved.")
    )
    assistant.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")

    turn = assistant.approve(THREAD)

    assert turn.answer == "That line was already resolved."
    result = json.loads(assistant.get_thread(THREAD).messages[2].content)
    assert result == {
        "error": "conflict",
        "status_code": 409,
        "reason": "Invoice line 2 is not needs_review",
    }


# ---------- reject ----------


def test_reject_posts_nothing_and_the_model_hears_why(make_assistant):
    api = FakeApi()
    assistant = make_assistant(api, propose_resolve(), AIMessage(content="OK, I left it."))
    assistant.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")

    turn = assistant.reject(THREAD, reason="Wrong product")

    assert turn.status == "answered"
    assert turn.answer == "OK, I left it."
    assert api.requests == []
    tool_result = assistant.get_thread(THREAD).messages[2]
    assert tool_result.status == "error"
    assert json.loads(tool_result.content) == {"error": "rejected", "reason": "Wrong product"}


def test_reject_answers_every_call_in_a_mixed_message(make_assistant):
    api = FakeApi()
    mixed = AIMessage(
        content="",
        tool_calls=[
            call("get_product", {"sku": "RICE-5"}, "r1"),
            call("resolve_review_item", {"invoice_id": 12, "line_no": 2, "sku": "RICE-5"}, "w1"),
        ],
    )
    assistant = make_assistant(api, mixed, AIMessage(content="Cancelled."))
    assistant.send_message(THREAD, "Check rice and resolve line 2 as RICE-5")

    assistant.reject(THREAD)

    results = [m for m in assistant.get_thread(THREAD).messages if m.type == "tool"]
    assert sorted(r.tool_call_id for r in results) == ["r1", "w1"]
    assert api.requests == []


# ---------- durability and concurrency ----------


def test_a_pause_survives_a_restart(clean_db):
    """Container 1 pauses; container 2 (new pool, new graph, new saver) approves."""
    api = FakeApi({("POST", RESOLVE_PATH): resolved()})
    first = build_assistant(api, clean_db, propose_resolve())
    first.send_message(THREAD, "Line 2 of invoice 12 is RICE-5")
    del first  # "the container stopped": nothing is left in memory

    new_pool = make_pool(get_settings())
    new_pool.open(wait=True)
    try:
        second = build_assistant(api, new_pool, AIMessage(content="Done after restart."))
        assert second.get_thread(THREAD).status == "pending_approval"

        turn = second.approve(THREAD)
    finally:
        new_pool.close()

    assert turn.answer == "Done after restart."
    assert posts(api) == [{"sku": "RICE-5"}]


def test_a_thread_that_is_already_running_is_busy(make_assistant, pool):
    assistant = make_assistant(FakeApi(), AIMessage(content="Hi"))

    with thread_lock(pool, THREAD):  # another request is mid-run
        with pytest.raises(ThreadBusy):
            assistant.send_message(THREAD, "Hello")


def test_a_looping_model_stops_with_a_clear_error(make_assistant):
    api = FakeApi({("GET", "/products/RICE-5"): (200, product("RICE-5", "Rice 5kg", 20, 5))})
    # The model asks for the same read forever (more replies than the recursion limit).
    loop = [
        AIMessage(content="", tool_calls=[call("get_product", {"sku": "RICE-5"}, f"r{i}")])
        for i in range(20)
    ]
    assistant = make_assistant(api, *loop)

    with pytest.raises(AgentGaveUp):
        assistant.send_message(THREAD, "How much rice?")

    assert assistant.get_thread(THREAD).status == "incomplete"


def test_a_new_message_after_an_incomplete_run_starts_fresh(make_assistant):
    api = FakeApi({("GET", "/products/RICE-5"): (200, product("RICE-5", "Rice 5kg", 20, 5))})
    loop = [
        AIMessage(content="", tool_calls=[call("get_product", {"sku": "RICE-5"}, f"r{i}")])
        for i in range(8)
    ]
    assistant = make_assistant(api, *loop, AIMessage(content="Rice 5kg: 20."))
    with pytest.raises(AgentGaveUp):
        assistant.send_message(THREAD, "How much rice?")

    turn = assistant.send_message(THREAD, "Just rice, please")

    assert turn.status == "answered"
    assert turn.answer == "Rice 5kg: 20."
