"""Request and response bodies for the threads endpoints."""

from typing import Any, Literal
from uuid import UUID

from langchain_core.messages import AnyMessage
from pydantic import BaseModel, Field

from app.agent.assistant import Turn

# ---------- requests ----------


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ToolCallEdit(BaseModel):
    tool_call_id: str
    # Only the arguments to change, e.g. {"sku": "RICE-10"}. The rest stay as proposed.
    args: dict[str, Any] = Field(min_length=1)


class ApproveIn(BaseModel):
    edits: list[ToolCallEdit] = Field(default_factory=list, max_length=20)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {e.tool_call_id: e.args for e in self.edits}


class RejectIn(BaseModel):
    # Passed to the model as the tool result, so it can tell the owner why.
    reason: str | None = Field(default=None, max_length=500)


# ---------- responses ----------


class ThreadCreated(BaseModel):
    thread_id: UUID


class ProposalOut(BaseModel):
    id: str  # the tool_call_id; use it in ApproveIn.edits
    tool: str
    args: dict[str, Any]


class TurnOut(BaseModel):
    thread_id: UUID
    status: Literal["answered", "pending_approval", "incomplete"]
    answer: str | None = None
    proposals: list[ProposalOut] = Field(default_factory=list)

    @classmethod
    def from_turn(cls, turn: Turn) -> "TurnOut":
        return cls(
            thread_id=turn.thread_id,
            status=turn.status,
            answer=turn.answer,
            proposals=turn.proposals,
        )


class MessageOut(BaseModel):
    role: Literal["user", "assistant", "tool"]
    text: str
    tool_calls: list[ProposalOut] = Field(default_factory=list)  # assistant asked for tools
    tool: str | None = None  # which tool produced this result

    @classmethod
    def from_message(cls, m: AnyMessage) -> "MessageOut":
        if m.type == "human":
            return cls(role="user", text=m.text)
        if m.type == "tool":
            return cls(role="tool", text=m.text, tool=m.name)
        calls = [{"id": c["id"], "tool": c["name"], "args": c["args"]} for c in m.tool_calls]
        return cls(role="assistant", text=m.text, tool_calls=calls)


class ThreadOut(TurnOut):
    messages: list[MessageOut]

    @classmethod
    def from_turn(cls, turn: Turn) -> "ThreadOut":
        base = TurnOut.from_turn(turn).model_dump()
        return cls(**base, messages=[MessageOut.from_message(m) for m in turn.messages])