"""LLM factory — returns DeepSeek V4 Flash via OpenAI-compatible API."""
import os

from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr


def get_llm(role: str = "analyst") -> BaseChatModel:  # noqa: ARG001
    """
    Always uses DeepSeek V4 Flash (deepseek-chat) via OpenAI-compatible API.
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=SecretStr(os.environ.get("DEEPSEEK_API_KEY", "")),
        base_url="https://api.deepseek.com/v1",
        temperature=0.3,
    )
