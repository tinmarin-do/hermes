"""Trader — converts debate verdict into a concrete trading decision."""
import os
from langchain_core.messages import HumanMessage, SystemMessage
from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are a crypto trader at an algorithmic trading firm.
You receive a debate verdict (BUY/SELL/HOLD) with confidence, analyst reports,
and the current regime. Your job is to:
1. Select the best symbol to act on (or decide HOLD for all).
2. Confirm or override the verdict based on the regime.
3. Produce a structured decision.

Always respond in this exact format:
ACTION: <BUY|SELL|HOLD>
SYMBOL: <symbol or NONE>
RATIONALE: <2-3 sentences>"""


def trader(state: HermesState) -> dict:
    llm = get_llm("decision")
    allowed = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")

    reports_text = "\n".join(
        f"- {r['symbol']}: {r['bias']} — {r['analysis'][:200]}"
        for r in state.get("analyst_reports", [])
    )

    response = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Debate verdict: {state.get('debate_verdict', 'HOLD')} "
            f"(confidence: {state.get('debate_confidence', 0.5):.0%})\n"
            f"Regime: {state.get('regime_summary', '')}\n"
            f"Analyst reports:\n{reports_text}\n"
            f"Allowed symbols: {allowed}\n\n"
            "Make your trading decision."
        )),
    ])

    text = response.content
    action = "HOLD"
    symbol = "NONE"

    for line in text.splitlines():
        if line.startswith("ACTION:"):
            action = line.split(":", 1)[1].strip()
        elif line.startswith("SYMBOL:"):
            symbol = line.split(":", 1)[1].strip()

    decision = {"action": action, "symbol": symbol, "rationale": text}
    return {
        "trader_decision": decision,
        "messages": [HumanMessage(content=f"[Trader]\n{text}")],
    }
