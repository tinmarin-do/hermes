"""Portfolio Manager — final decision gate. §8.7.2 brake enforcement."""

import os

from langchain_core.messages import HumanMessage, SystemMessage

from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are the Portfolio Manager. You have the final word on every trade.
You receive the quant thesis, debate verdict, trader's decision, risk team's synthesis,
and approval status.

RULES (programmatically enforced — override will be discarded):
1. If risk is NOT approved → MUST HOLD (no exceptions).
2. If the debate verdict is HOLD → MUST HOLD (freno asimétrico: PM never originates).
3. If risk IS approved AND verdict ≠ HOLD AND trader action ≠ HOLD →
   you may confirm or reduce the trade. You may never increase size beyond the trader.

Respond in this format:
FINAL_ACTION: <BUY|SELL|HOLD>
FINAL_SYMBOL: <symbol or NONE>
FINAL_SIZE_USD: <number>
RATIONALE: <2-3 sentences>"""


def portfolio_manager(state: HermesState) -> dict:
    llm = get_llm("decision")
    decision = state.get("trader_decision", {})
    approved = state.get("risk_approved", False)
    verdict = state.get("debate_verdict", "HOLD")
    max_positions = int(os.environ.get("HERMES_MAX_POSITIONS", "6"))

    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM),
            HumanMessage(
                content=(
                    f"Debate verdict: {verdict}\n"
                    f"Trader decision: {decision.get('action')} {decision.get('symbol')} "
                    f"${decision.get('size_usd', 0):.2f}\n"
                    f"Risk approved: {'YES' if approved else 'NO — must HOLD'}\n"
                    f"Risk synthesis: {state.get('risk_synthesis', '')}\n"
                    f"Max simultaneous positions: {max_positions}\n\n"
                    "Make the final call. If verdict is HOLD or risk not approved, you MUST HOLD."
                )
            ),
        ]
    )

    text = response.content

    # ── Programmatic guardrails (freno asimétrico) ──
    if not approved:
        return {
            "pm_decision": {
                "action": "HOLD",
                "symbol": "NONE",
                "size_usd": 0.0,
                "rationale": f"REJECTED by risk guardrails. Response:\n{text}",
            },
            "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
        }

    if verdict == "HOLD":
        return {
            "pm_decision": {
                "action": "HOLD",
                "symbol": "NONE",
                "size_usd": 0.0,
                "rationale": f"Debate verdict HOLD — PM brake. Response:\n{text}",
            },
            "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
        }

    # Parse LLM response
    pm = {"action": "HOLD", "symbol": "NONE", "size_usd": 0.0, "rationale": text}
    for line in text.splitlines():
        if line.startswith("FINAL_ACTION:"):
            parsed = line.split(":", 1)[1].strip()
            if parsed in ("BUY", "SELL"):
                pm["action"] = parsed
        elif line.startswith("FINAL_SYMBOL:"):
            pm["symbol"] = line.split(":", 1)[1].strip()
        elif line.startswith("FINAL_SIZE_USD:"):
            try:
                pm["size_usd"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    # Clamp: PM can reduce but never increase beyond trader's size
    trader_symbol = decision.get("symbol", "NONE")
    trader_size = decision.get("size_usd", 0.0)
    if pm["symbol"] != trader_symbol and trader_symbol != "NONE":
        pm["symbol"] = trader_symbol
    pm["size_usd"] = round(min(pm["size_usd"], trader_size), 2)

    return {
        "pm_decision": pm,
        "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
    }
