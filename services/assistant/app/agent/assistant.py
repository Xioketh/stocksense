"""The approval flow on top of the graph: send, approve (with edits), reject, read.

The HTTP router is thin; everything about threads and the pause lives here,
so tests can drive it without HTTP.

How the pause works (Lesson 6): the graph is compiled with
interrupt_before=["write_tools"]. When the model proposes a write, the run
stops and the checkpoint's `next` is ("write_tools",). That checkpoint IS the
approval status: nothing else is stored, so there's nothing to get out of sync.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import StateSnapshot
from psycopg_pool import ConnectionPool

from app.agent.graph import run_config
from app.agent.nodes import LLM, WRITE_TOOLS
from app.agent.thread_lock import thread_lock
from app.errors import AgentGaveUp, ApprovalPending, InvalidEdit, NothingToApprove, ThreadNotFound

logger = logging.getLogger(__name__)

Status = Literal["answered", "pending_approval", "incomplete"]

DEFAULT_REJECT_REASON = "The owner rejected this change."


@dataclass
class Turn:
    """What a client needs after every call."""

    thread_id: str
    status: Status
    answer: str | None = None  # the assistant's reply, when status is "answered"
    proposals: list[dict[str, Any]] = field(default_factory=list)  # [{id, tool, args}]
    messages: list[AnyMessage] = field(default_factory=list)  # filled only by get_thread


class Assistant:
    def __init__(self, graph: CompiledStateGraph, pool: ConnectionPool) -> None:
        self.graph = graph
        self.pool = pool

    # ---------- reads ----------

    def get_thread(self, thread_id: str) -> Turn:
        state = self._state(thread_id)
        if not state.values:  # no checkpoint = this thread never got a message
            raise ThreadNotFound()
        turn = _turn(thread_id, state)
        turn.messages = state.values["messages"]
        return turn

    # ---------- runs (each one holds the thread lock) ----------

    def send_message(self, thread_id: str, text: str) -> Turn:
        with thread_lock(self.pool, thread_id):
            if _is_paused(self._state(thread_id)):
                # The pending proposal has no ToolMessage yet. A new HumanMessage
                # after it would be an invalid history for Gemini.
                raise ApprovalPending()
            self._run({"messages": [HumanMessage(text)]}, thread_id)
            return _turn(thread_id, self._state(thread_id))

    def approve(self, thread_id: str, edits: dict[str, dict[str, Any]] | None = None) -> Turn:
        """Run the paused write calls. edits: {tool_call_id: {arg: new value}}."""
        with thread_lock(self.pool, thread_id):
            proposal = self._pending_proposal(thread_id)
            if edits:
                self._apply_edits(thread_id, proposal, edits)
            logger.info("proposal approved", extra={"thread_id": thread_id, "edited": bool(edits)})
            self._run(None, thread_id)  # None = resume from the checkpoint (Lesson 6)
            return _turn(thread_id, self._state(thread_id))

    def reject(self, thread_id: str, reason: str | None = None) -> Turn:
        """Answer every proposed call with a "rejected" result, then let the LLM reply."""
        with thread_lock(self.pool, thread_id):
            proposal = self._pending_proposal(thread_id)
            content = json.dumps({"error": "rejected", "reason": reason or DEFAULT_REJECT_REASON})
            results = [
                ToolMessage(content, tool_call_id=c["id"], name=c["name"], status="error")
                for c in proposal.tool_calls
            ]
            # as_node=WRITE_TOOLS: the checkpoint looks as if write_tools ran and
            # returned these. Its normal edge then goes to llm. Nothing is POSTed.
            self.graph.update_state(
                run_config(thread_id), {"messages": results}, as_node=WRITE_TOOLS
            )
            logger.info("proposal rejected", extra={"thread_id": thread_id})
            self._run(None, thread_id)
            return _turn(thread_id, self._state(thread_id))

    # ---------- helpers ----------

    def _state(self, thread_id: str) -> StateSnapshot:
        return self.graph.get_state(run_config(thread_id))

    def _run(self, graph_input: dict | None, thread_id: str) -> None:
        try:
            self.graph.invoke(graph_input, run_config(thread_id))
        except GraphRecursionError as exc:
            logger.warning("recursion limit reached", extra={"thread_id": thread_id})
            raise AgentGaveUp() from exc

    def _pending_proposal(self, thread_id: str) -> AIMessage:
        state = self._state(thread_id)
        if not state.values:
            raise ThreadNotFound()
        if not _is_paused(state):
            raise NothingToApprove()
        return state.values["messages"][-1]

    def _apply_edits(
        self, thread_id: str, proposal: AIMessage, edits: dict[str, dict[str, Any]]
    ) -> None:
        known = {c["id"] for c in proposal.tool_calls}
        unknown = sorted(set(edits) - known)
        if unknown:
            raise InvalidEdit(f"Unknown tool_call_id {unknown}. Pending ids: {sorted(known)}.")
        calls = [
            {**c, "args": {**c["args"], **edits.get(c["id"], {})}} for c in proposal.tool_calls
        ]
        # A COPY of the same message: same id (so add_messages REPLACES it instead
        # of appending), and same additional_kwargs (Gemini's thought signatures,
        # which it needs back on the next call). Only tool_calls change.
        edited = proposal.model_copy(update={"tool_calls": calls})
        # as_node=LLM: as if the model had proposed the edited version. The router
        # runs again, still picks write_tools, and the pause stays in place.
        self.graph.update_state(run_config(thread_id), {"messages": [edited]}, as_node=LLM)


def _is_paused(state: StateSnapshot) -> bool:
    return state.next == (WRITE_TOOLS,)


def _turn(thread_id: str, state: StateSnapshot) -> Turn:
    messages = state.values.get("messages", [])
    last = messages[-1] if messages else None
    if _is_paused(state):
        proposals = [{"id": c["id"], "tool": c["name"], "args": c["args"]} for c in last.tool_calls]
        return Turn(thread_id, "pending_approval", proposals=proposals)
    if isinstance(last, AIMessage) and not last.tool_calls:
        return Turn(thread_id, "answered", answer=last.text)
    # A run that stopped early (model error, recursion limit). A new message starts fresh.
    return Turn(thread_id, "incomplete")
