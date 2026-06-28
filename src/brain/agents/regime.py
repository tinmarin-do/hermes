"""RegimeClassifier — summarizes Gold signals into a human-readable regime brief."""

from langchain_core.messages import HumanMessage, SystemMessage

from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are a quantitative regime classifier for a crypto trading system.
You receive statistical signals (Hurst exponent, GARCH volatility, spread, returns)
and produce a concise regime brief for downstream trading agents.
Be precise, use numbers, and classify each asset clearly."""


def regime_classifier(state: HermesState) -> dict:
    signals = state["gold_signals"]

    signal_text = "\n".join(
        f"- {s['symbol']}: regime={s['regime']} (conf={s['regime_conf']:.2f}), "
        f"hurst={s['features']['hurst']}, garch_vol={s['features']['garch_vol']}, "
        f"returns_1h={s['features']['returns_1h']}, returns_24h={s['features']['returns_24h']}"
        for s in signals
    )

    llm = get_llm("analyst")
    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM),
            HumanMessage(
                content=f"Classify the current market regime for:\n{signal_text}\n\n"
                "Produce a 3-5 sentence brief covering: dominant regime, "
                "which assets are trending vs mean-reverting, volatility level, "
                "and overall market risk tone."
            ),
        ]
    )

    summary = response.content
    return {
        "regime_summary": summary,
        "messages": [HumanMessage(content=f"[RegimeClassifier]\n{summary}")],
    }
