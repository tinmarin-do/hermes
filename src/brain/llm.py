"""LLM factory — returns DeepSeek V4 Flash via OpenAI-compatible API."""


from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr


def get_llm(role: str = "analyst") -> BaseChatModel:  # noqa: ARG001
    """
    Always uses DeepSeek V4 Flash (deepseek-chat) via OpenAI-compatible API.

    Every model attaches CostCallbackHandler so token usage is routed to the
    run's active CostMeter (see src.brain.cost_meter). Metering is a no-op when
    no run is active, so this is safe in any context.
    """
    from langchain_openai import ChatOpenAI

    from src.brain.cost_meter import CostCallbackHandler
    from src.secrets import get_secret

    return ChatOpenAI(
        model="deepseek-chat",
        api_key=SecretStr(get_secret("DEEPSEEK_API_KEY")),
        base_url="https://api.deepseek.com/v1",
        temperature=0.3,
        callbacks=[CostCallbackHandler()],
    )
