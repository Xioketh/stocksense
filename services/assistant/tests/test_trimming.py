from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.trimming import trim_history


def turn(question: str, call_id: str, result_size: int) -> list:
    """One owner turn: question -> tool call -> tool result -> answer."""
    call = {"name": "get_product", "args": {"sku": "RICE-5"}, "id": call_id, "type": "tool_call"}
    return [
        HumanMessage(question),
        AIMessage(content="", tool_calls=[call]),
        ToolMessage("x" * result_size, tool_call_id=call_id, name="get_product"),
        AIMessage(content=f"answer to {question}"),
    ]


def test_short_history_is_sent_whole():
    messages = [*turn("q1", "a", 100), HumanMessage("q2")]

    assert trim_history(messages, max_tokens=8_000) == messages


def test_old_turns_are_dropped_and_the_cut_is_at_a_human_message():
    messages = [*turn("q1", "a", 2_000), *turn("q2", "b", 400), HumanMessage("q3")]

    kept = trim_history(messages, max_tokens=300)

    assert kept[0].content == "q2"  # q1's turn is gone, q2's turn is whole
    assert [m.type for m in kept] == ["human", "ai", "tool", "ai", "human"]


def test_a_tool_result_never_loses_its_call():
    messages = [*turn("q1", "a", 400), *turn("q2", "b", 400), HumanMessage("q3")]

    for budget in (20, 50, 150, 300, 1_000):
        kept = trim_history(messages, max_tokens=budget)
        call_ids = {c["id"] for m in kept if m.type == "ai" for c in m.tool_calls}
        result_ids = {m.tool_call_id for m in kept if m.type == "tool"}
        assert result_ids == call_ids, budget
        assert kept[0].type == "human", budget


def test_an_oversized_current_turn_is_kept_whole_not_emptied():
    messages = [*turn("q1", "a", 100), *turn("q2", "b", 40_000)[:3]]  # q2 still running

    kept = trim_history(messages, max_tokens=100)

    assert [m.type for m in kept] == ["human", "ai", "tool"]
    assert kept[0].content == "q2"