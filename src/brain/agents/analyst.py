"""Technical Analyst — one per symbol, runs in parallel."""

from langchain_core.messages import HumanMessage, SystemMessage

from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are a technical analyst specializing in crypto markets.
You analyze statistical regime signals and technical context to produce a concise
investment thesis for a single asset. Focus on: regime interpretation, momentum,
volatility risk, and a directional bias (bullish / bearish / neutral) with rationale."""


def make_analyst(symbol: str):
    """Factory — returns a LangGraph node function for the given symbol."""

    def analyst(state: HermesState) -> dict:
        signal = next((s for s in state["gold_signals"] if s["symbol"] == symbol), None)
        if signal is None:
            return {}

        llm = get_llm("analyst")
        regime_ctx = state.get("regime_summary", "No regime summary available.")
        response = llm.invoke(
            [
                SystemMessage(content=SYSTEM),
                HumanMessage(
                    content=(
                        f"Asset: {symbol}\n"
                        f"Regime: {signal['regime']} (confidence: {signal['regime_conf']:.2f})\n"
                        f"Hurst: {signal['features']['hurst']} | "
                        f"GARCH vol: {signal['features']['garch_vol']} | "
                        f"Spread: {signal['features']['spread']}\n"
                        f"Return 1h: {signal['features']['returns_1h']} | "
                        f"Return 24h: {signal['features']['returns_24h']}\n\n"
                        f"Market context: {regime_ctx}\n\n"
                        "Produce a 3-5 sentence technical analysis report with a clear "
                        "directional bias: BULLISH, BEARISH, or NEUTRAL."
                    )
                ),
            ]
        )

        report = {
            "symbol": symbol,
            "regime": signal["regime"],
            "bias": _extract_bias(response.content),
            "analysis": response.content,
        }

        return {
            "analyst_reports": [report],
            "messages": [HumanMessage(content=f"[Analyst:{symbol}]\n{response.content}")],
        }

    analyst.__name__ = f"analyst_{symbol.replace('/', '_')}"
    return analyst


def _extract_bias(text: str) -> str:
    text_upper = text.upper()
    if "BULLISH" in text_upper:
        return "BULLISH"
    if "BEARISH" in text_upper:
        return "BEARISH"
    return "NEUTRAL"
