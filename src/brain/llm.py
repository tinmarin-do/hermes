"""LLM factory — returns the right model based on HERMES_MODE."""
import os
from langchain_core.language_models import BaseChatModel


def get_llm(role: str = "analyst") -> BaseChatModel:
    """
    local  → Ollama (free, CPU)
    cloud  → DeepSeek / OpenAI (paid, faster)

    role: "analyst" = smaller/faster model
          "decision" = larger/deeper model (trader, risk, PM)
    """
    mode = os.environ.get("HERMES_MODE", "local")

    if mode == "local":
        from langchain_ollama import ChatOllama
        model = (
            os.environ.get("OLLAMA_MODEL_ANALYST", "llama3.2:3b")
            if role == "analyst"
            else os.environ.get("OLLAMA_MODEL_PM", "llama3.2:3b")
        )
        return ChatOllama(
            model=model,
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0.3,
        )

    # cloud mode — DeepSeek for all roles via OpenAI-compatible API
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com/v1",
        temperature=0.3,
    )
