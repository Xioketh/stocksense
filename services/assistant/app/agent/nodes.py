import logging
from collections.abc import Callable

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END
from pydantic import ValidationError

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.state import AgentState
from app.agent.trimming import trim_history

logger = logging.getLogger(__name__)

# Node names, used by the graph, the router and interrupt_before.
LLM = "llm"
READ_TOOLS = "read_tools"
WRITE_TOOLS = "write_tools"


def make_llm_node(model: Runnable[LanguageModelInput, AIMessage]) -> Callable[[AgentState], dict]:
    def llm(state: AgentState) -> dict:
        # The system prompt is added here on every call, not stored in state,
        # so changing the prompt never needs a migration of saved threads.
        # Only recent whole turns are sent; the checkpoint keeps everything.
        history = trim_history(state["messages"])
        response = model.invoke([SystemMessage(SYSTEM_PROMPT), *history])
        return {"messages": [response]}

    return llm


def run_tool_calls(message: AIMessage, allowed: dict[str, BaseTool]) -> list[ToolMessage]:
    """Run every tool call in one AIMessage, one after another.

    Every call gets exactly ONE ToolMessage with its tool_call_id, even when it
    fails. Gemini (like every chat model) refuses the next turn if a call has
    no answer, so a failed call must become a message, not an exception.
    """
    results = []
    for call in message.tool_calls:
        tool = allowed.get(call["name"])
        if tool is None:
            # Unknown name, or a write tool that reached the read node: refuse, explain.
            content = f'Tool "{call["name"]}" is not available here. Use one of: {sorted(allowed)}.'
            logger.warning("tool refused", extra={"tool": call["name"]})
            results.append(_error(call, content))
            continue
        try:
            output = tool.invoke(call["args"])
        except ValidationError as exc:
            # Wrong or missing arguments: tell the LLM so it can fix them.
            logger.info("tool bad arguments", extra={"tool": call["name"]})
            results.append(_error(call, f"Invalid arguments for {call['name']}: {exc}"))
            continue
        except Exception:
            # A bug on our side. Log it in full; give the LLM a short message.
            logger.exception("tool crashed", extra={"tool": call["name"]})
            results.append(_error(call, f"{call['name']} failed unexpectedly."))
            continue
        logger.info("tool ran", extra={"tool": call["name"]})
        results.append(ToolMessage(content=output, tool_call_id=call["id"], name=call["name"]))
    return results


def _error(call: dict, content: str) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=call["id"], name=call["name"], status="error")


def make_tool_node(allowed: list[BaseTool]) -> Callable[[AgentState], dict]:
    by_name = {t.name: t for t in allowed}

    def tool_node(state: AgentState) -> dict:
        last = state["messages"][-1]
        return {"messages": run_tool_calls(last, by_name)}

    return tool_node


def make_router(write_names: set[str]) -> Callable[[AgentState], str]:
    def route_after_llm(state: AgentState) -> str:
        last = state["messages"][-1]
        if not last.tool_calls:
            return END
        # ANY write call sends the WHOLE message to write_tools (which can also
        # run its reads), so every call is answered before the next LLM turn.
        if any(call["name"] in write_names for call in last.tool_calls):
            return WRITE_TOOLS
        return READ_TOOLS

    return route_after_llm