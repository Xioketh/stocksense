"""Keep only recent WHOLE turns in what we send to the model.

The checkpoint keeps the full thread; this only shrinks the request, so token
cost stays flat on long conversations.

A "turn" starts at a HumanMessage and runs until the next one:
    human -> ai(tool_calls) -> tool -> ... -> ai(answer)
Cutting only at turn boundaries means a ToolMessage never loses the AIMessage
that asked for it (Gemini rejects that history), and the history always starts
with a human message.
"""

from langchain_core.messages import AnyMessage
from langchain_core.messages.utils import count_tokens_approximately

# Rough budget for the history (system prompt and tool schemas come on top).
DEFAULT_MAX_TOKENS = 8_000


def _split_turns(messages: list[AnyMessage]) -> list[list[AnyMessage]]:
    turns: list[list[AnyMessage]] = []
    for m in messages:
        if m.type == "human" or not turns:
            turns.append([])
        turns[-1].append(m)
    return turns


def trim_history(
    messages: list[AnyMessage], max_tokens: int = DEFAULT_MAX_TOKENS
) -> list[AnyMessage]:
    """The newest whole turns that fit in max_tokens.

    The current (last) turn is always kept, even if it alone is over budget:
    dropping it would send the model an empty or broken history.
    """
    turns = _split_turns(messages)
    if not turns:
        return []

    kept = [turns[-1]]
    used = count_tokens_approximately(turns[-1])
    for t in reversed(turns[:-1]):
        cost = count_tokens_approximately(t)
        if used + cost > max_tokens:
            break  # stop at the first turn that doesn't fit; never skip over one
        kept.append(t)
        used += cost

    return [m for t in reversed(kept) for m in t]
