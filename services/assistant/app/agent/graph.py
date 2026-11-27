from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes import LLM, READ_TOOLS, WRITE_TOOLS, make_llm_node, make_router, make_tool_node
from app.agent.state import AgentState
from app.tools import ToolSet

# Max graph steps per run. A normal question is ~3 (llm -> tools -> llm);
# this stops a looping model with a GraphRecursionError instead of burning tokens.
RECURSION_LIMIT = 15


def build_graph(
    model: Runnable[LanguageModelInput, AIMessage],
    tools: ToolSet,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """llm -> (read_tools | write_tools | END); both tool nodes go back to llm.

    model: a chat model with tools already bound (tests pass a fake model).
    checkpointer is REQUIRED: the pause before write_tools only works with one.
    A3 uses InMemorySaver; A4 switches to PostgresSaver.
    """
    graph = StateGraph(AgentState)
    graph.add_node(LLM, make_llm_node(model))
    graph.add_node(READ_TOOLS, make_tool_node(tools.read))
    graph.add_node(WRITE_TOOLS, make_tool_node(tools.all))  # mixed messages need the reads too

    graph.add_edge(START, LLM)
    graph.add_conditional_edges(
        LLM,
        make_router(tools.write_names),
        {READ_TOOLS: READ_TOOLS, WRITE_TOOLS: WRITE_TOOLS, END: END},
    )
    graph.add_edge(READ_TOOLS, LLM)
    graph.add_edge(WRITE_TOOLS, LLM)

    # Writes never run without a stop, from the very first version.
    return graph.compile(checkpointer=checkpointer, interrupt_before=[WRITE_TOOLS])


def run_config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT}