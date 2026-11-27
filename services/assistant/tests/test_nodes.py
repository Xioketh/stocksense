import logging

from langchain_core.messages import AIMessage
from langgraph.graph import END

from app.agent.nodes import READ_TOOLS, WRITE_TOOLS, make_router, run_tool_calls
from app.tools import make_tools
from tests.fake_api import FakeApi, product


def call(name: str, args: dict, call_id: str = "call-1") -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def test_every_call_gets_its_own_tool_message():
    api = FakeApi(
        {
            ("GET", "/products/RICE-5"): (200, product("RICE-5", "Rice 5kg", 20, 5)),
            ("GET", "/products/SUGAR-1"): (200, product("SUGAR-1", "Sugar 1kg", 3, 5)),
        }
    )
    tools = make_tools(api.client())
    message = AIMessage(
        content="",
        tool_calls=[
            call("get_product", {"sku": "RICE-5"}, "a"),
            call("get_product", {"sku": "SUGAR-1"}, "b"),
        ],
    )

    results = run_tool_calls(message, {t.name: t for t in tools.read})

    assert [r.tool_call_id for r in results] == ["a", "b"]
    assert all(r.status == "success" for r in results)


def test_unknown_tool_name_becomes_feedback():
    tools = make_tools(FakeApi().client())
    message = AIMessage(content="", tool_calls=[call("delete_everything", {})])

    [result] = run_tool_calls(message, {t.name: t for t in tools.read})

    assert result.status == "error"
    assert "not available" in result.content
    assert result.tool_call_id == "call-1"


def test_write_tool_reaching_the_read_node_is_refused_and_never_runs():
    api = FakeApi()
    tools = make_tools(api.client())
    message = AIMessage(
        content="",
        tool_calls=[call("resolve_review_item", {"invoice_id": 1, "line_no": 1, "sku": "X"})],
    )

    [result] = run_tool_calls(message, {t.name: t for t in tools.read})

    assert result.status == "error"
    assert api.requests == []  # no POST was sent


def test_bad_arguments_become_feedback():
    tools = make_tools(FakeApi().client())
    message = AIMessage(content="", tool_calls=[call("get_invoice", {"invoice_id": "twelve"})])

    [result] = run_tool_calls(message, {t.name: t for t in tools.read})

    assert result.status == "error"
    assert result.content.startswith("Invalid arguments for get_invoice")


def test_a_crashing_tool_is_logged_and_still_answered(caplog):
    # A 200 with an unexpected body makes the tool raise KeyError (a bug on our side).
    api = FakeApi({("GET", "/products"): (200, {"unexpected": True})})
    tools = make_tools(api.client())
    message = AIMessage(content="", tool_calls=[call("list_low_stock", {})])

    with caplog.at_level(logging.ERROR):
        [result] = run_tool_calls(message, {t.name: t for t in tools.read})

    assert result.status == "error"
    assert "tool crashed" in caplog.text


def test_router():
    route = make_router({"resolve_review_item"})
    read = call("get_product", {"sku": "RICE-5"}, "a")
    write = call("resolve_review_item", {"invoice_id": 1, "line_no": 1, "sku": "X"}, "b")

    def state(*calls):
        return {"messages": [AIMessage(content="", tool_calls=list(calls))]}

    assert route({"messages": [AIMessage(content="Done.")]}) == END
    assert route(state(read)) == READ_TOOLS
    assert route(state(write)) == WRITE_TOOLS
    assert route(state(read, write)) == WRITE_TOOLS  # mixed: the whole message pauses
