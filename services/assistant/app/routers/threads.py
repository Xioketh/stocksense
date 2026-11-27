"""Threads: one conversation each, saved in Postgres, resumable after a restart.

Endpoints are plain `def` (sync). FastAPI runs them in its thread pool, so a
slow Gemini call blocks one worker thread, not the whole server.
"""

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.agent.assistant import Assistant
from app.schemas import ApproveIn, MessageIn, RejectIn, ThreadCreated, ThreadOut, TurnOut
from app.security import require_api_key

router = APIRouter(prefix="/threads", tags=["threads"], dependencies=[Depends(require_api_key)])


def get_assistant(request: Request) -> Assistant:
    """The Assistant built once at startup (main.py lifespan). Tests override this."""
    return request.app.state.assistant


@router.post("", status_code=status.HTTP_201_CREATED)
def create_thread() -> ThreadCreated:
    """A new thread id. Nothing is saved until its first message."""
    return ThreadCreated(thread_id=uuid.uuid4())


@router.post("/{thread_id}/messages")
def send_message(
    thread_id: UUID, body: MessageIn, assistant: Assistant = Depends(get_assistant)
) -> TurnOut:
    """Ask something. Returns the answer, or the proposed change waiting for approval.

    409 if a change is already waiting: approve or reject it first.
    """
    return TurnOut.from_turn(assistant.send_message(str(thread_id), body.text))


@router.get("/{thread_id}")
def get_thread(thread_id: UUID, assistant: Assistant = Depends(get_assistant)) -> ThreadOut:
    return ThreadOut.from_turn(assistant.get_thread(str(thread_id)))


@router.post("/{thread_id}/approve")
def approve(
    thread_id: UUID,
    body: ApproveIn | None = None,
    assistant: Assistant = Depends(get_assistant),
) -> TurnOut:
    """Run the waiting change. Optional edits change arguments first (e.g. a different SKU)."""
    edits = body.as_dict() if body else None
    return TurnOut.from_turn(assistant.approve(str(thread_id), edits))


@router.post("/{thread_id}/reject")
def reject(
    thread_id: UUID,
    body: RejectIn | None = None,
    assistant: Assistant = Depends(get_assistant),
) -> TurnOut:
    """Cancel the waiting change. Nothing is sent to the API; the assistant replies."""
    return TurnOut.from_turn(assistant.reject(str(thread_id), body.reason if body else None))