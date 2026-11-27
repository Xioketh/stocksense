"""Talk to the agent from a terminal (A3 only; A4 adds the HTTP endpoints).

Run INSIDE the assistant container, so the API is at http://api:8080:
    docker compose exec assistant python -m app.cli "What's running low?"
    docker compose exec assistant python -m app.cli          (chat until you type "exit")

Memory is InMemorySaver: one thread per run, gone when the process ends.
A proposed write stops the graph; approving it comes in A4.
"""

import sys
import uuid

from langgraph.checkpoint.memory import InMemorySaver

from app.agent.graph import build_graph, run_config
from app.agent.model import make_chat_model
from app.agent.nodes import WRITE_TOOLS
from app.config import get_settings
from app.logging_config import setup_logging
from app.tools import make_tools
from app.tools.api_client import StockSenseClient


def ask(graph, config, question: str) -> bool:
    """Run one question. Returns True if the graph paused before a write."""
    # stream_mode="updates": one item per finished node, so you see each step.
    for update in graph.stream({"messages": [("user", question)]}, config, stream_mode="updates"):
        for node, change in update.items():
            if not change:  # the "__interrupt__" item has no messages
                continue
            for msg in change["messages"]:
                if msg.type == "ai" and msg.tool_calls:
                    for call in msg.tool_calls:
                        print(f"  [{node}] wants {call['name']}({call['args']})")
                elif msg.type == "tool":
                    print(f"  [{node}] {msg.name} -> {msg.content[:200]}")

    state = graph.get_state(config)
    if state.next == (WRITE_TOOLS,):
        print("\nPAUSED: the agent proposes a change. Nothing has been changed.")
        print("Approve / edit / reject arrives in A4.\n")
        return True
    print(f"\nAssistant: {state.values['messages'][-1].text}\n")
    return False


def new_thread():
    return run_config(thread_id=str(uuid.uuid4()))


def main() -> None:
    settings = get_settings()
    setup_logging("WARNING")  # keep the terminal readable; LangSmith has the details

    client = StockSenseClient.from_settings(settings)
    tools = make_tools(client)
    graph = build_graph(make_chat_model(settings, tools.all), tools, InMemorySaver())
    config = new_thread()

    try:
        if len(sys.argv) > 1:
            ask(graph, config, " ".join(sys.argv[1:]))
            return
        while (question := input("You: ").strip()).lower() not in {"exit", "quit"}:
            if question and ask(graph, config, question):
                # A paused thread can't take a new message (its proposal has no
                # answer yet), so continue in a fresh thread. A4 returns 409 instead.
                print("(Starting a new conversation.)")
                config = new_thread()
    finally:
        client.close()


if __name__ == "__main__":
    main()