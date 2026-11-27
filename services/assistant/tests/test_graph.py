"""The whole graph with a scripted fake model: no Gemini, no network.

GenericFakeChatModel returns the messages we give it, in order. It can't
bind tools (bind_tools raises NotImplementedError), which is why build_graph
takes a model that already has its tools bound.
"""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import build_graph, run_config
from app.agent.nodes import WRITE_TOOLS
from app.tools import make_tools
from tests.fake_api import FakeApi, product


def fake_model(*replies: AIMessage) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter(replies))


def tool_call(name: str, args: dict, call_id: str) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def run(api: FakeApi, model: GenericFakeChatModel, question: str):
    graph = build_graph(model, make_tools(api.client()), InMemorySaver())
    config = run_config("test-thread")
    graph.invoke({"messages": [("user", question)]}, config)
    return graph.get_state(config)


def test_parallel_reads_then_answer():
    api = FakeApi(
        {
            ("GET", "/products/RICE-5"): (200, product("RICE-5", "Rice 5kg", 20, 5)),
            ("GET", "/products/SUGAR-1"): (200, product("SUGAR-1", "Sugar 1kg", 3, 5)),
        }
    )
    model = fake_model(
        AIMessage(
            content="",
            tool_calls=[
                tool_call("get_product", {"sku": "RICE-5"}, "a"),
                tool_call("get_product", {"sku": "SUGAR-1"}, "b"),
            ],
        ),
        AIMessage(content="Rice: 20. Sugar: 3 (low)."),
    )

    state = run(api, model, "How much rice and sugar?")

    assert state.next == ()  # finished, not paused
    types = [m.type for m in state.values["messages"]]
    assert types == ["human", "ai", "tool", "tool", "ai"]
    assert state.values["messages"][-1].content == "Rice: 20. Sugar: 3 (low)."
    assert api.methods() == ["GET", "GET"]


def test_a_write_proposal_pauses_before_anything_changes():
    api = FakeApi()
    model = fake_model(
        AIMessage(
            content="",
            tool_calls=[
                tool_call(
                    "resolve_review_item", {"invoice_id": 12, "line_no": 2, "sku": "RICE-5"}, "w"
                )
            ],
        )
    )

    state = run(api, model, "Line 2 of invoice 12 is RICE-5")

    assert state.next == (WRITE_TOOLS,)
    assert state.values["messages"][-1].tool_calls[0]["name"] == "resolve_review_item"
    assert api.requests == []  # paused BEFORE the POST


def test_a_mixed_message_pauses_as_a_whole():
    api = FakeApi()
    model = fake_model(
        AIMessage(
            content="",
            tool_calls=[
                tool_call("get_product", {"sku": "RICE-5"}, "r"),
                tool_call(
                    "resolve_review_item", {"invoice_id": 12, "line_no": 2, "sku": "RICE-5"}, "w"
                ),
            ],
        )
    )

    state = run(api, model, "Check rice and resolve line 2 of invoice 12 as RICE-5")

    assert state.next == (WRITE_TOOLS,)
    assert api.requests == []  # even the read waits for the decision
