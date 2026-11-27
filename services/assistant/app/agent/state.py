from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """The whole graph state: just the conversation.

    add_messages appends new messages, but a message with an id that is
    already in the list REPLACES it. A4's "edit" flow needs that: the edited
    proposal replaces the original instead of being added twice.

    Kept OUT of state on purpose: API keys, live stock numbers (always fetched
    fresh by tools) and approval status (the graph's pause is the status).
    """

    messages: Annotated[list[AnyMessage], add_messages]
