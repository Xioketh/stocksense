"""Errors the assistant raises on purpose, each with its HTTP status.

The service layer raises them; ONE handler in main.py turns any of them into
{"detail": "..."} with the right status, the same shape the API uses.
"""


class AssistantError(Exception):
    status_code = 500
    detail = "Something went wrong."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.detail)
        if detail:
            self.detail = detail


class ThreadNotFound(AssistantError):
    status_code = 404
    detail = "Thread not found. Send a message to start it."


class ApprovalPending(AssistantError):
    status_code = 409
    detail = "A change is waiting for approval. Approve or reject it first."


class NothingToApprove(AssistantError):
    status_code = 409
    detail = "This thread has no change waiting for approval."


class ThreadBusy(AssistantError):
    status_code = 409
    detail = "This thread is already running. Try again in a moment."


class InvalidEdit(AssistantError):
    status_code = 400


class AgentGaveUp(AssistantError):
    status_code = 500
    detail = "The assistant took too many steps and stopped. Try rephrasing the question."