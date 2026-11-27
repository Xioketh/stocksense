from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import Settings

# Seconds for one Gemini call, and how many times to retry a failed one.
GEMINI_TIMEOUT_SECONDS = 30
GEMINI_MAX_RETRIES = 2


def make_chat_model(
    settings: Settings, tools: list[BaseTool]
) -> Runnable[LanguageModelInput, AIMessage]:
    """Gemini with every tool bound (read AND write).

    The model must SEE the write tool to propose it. Seeing it is safe:
    the graph decides what actually runs, and it pauses before writes.

    Temperature stays at Gemini 3's default (1.0). Google advises against
    lowering it for Gemini 3 models (it can cause looping), so we don't set it.
    """
    model = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,  # SecretStr: never printed in logs
        timeout=GEMINI_TIMEOUT_SECONDS,
        max_retries=GEMINI_MAX_RETRIES,
    )
    return model.bind_tools(tools)
