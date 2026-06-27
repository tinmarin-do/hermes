"""Portfolio Manager — final decision gate."""
import os
from langchain_core.messages import HumanMessage, SystemMessage
from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are the Portfolio Manager. You have the final word on every trade.
You receive the debate verdict, the trader's decision, the risk team's synthesis,
and approval status.

RULES (programmatically enforced — override will be discarded):
1. If risk is NOT approved → MUST HOLD (no exceptions).
2. If the debate verdict is HOLD → MUST HOLD (freno asimétrico: PM never originates).
3. If risk IS approved AND verdict ≠ HOLD → you may confirm or reduce the trade.
   You may never increase size beyond what the trader proposed.

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
    max_positions = int(os.environ.get("HERMES_MAX_POSITIONS", "2"))

    response = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Debate verdict: {verdict}\n"
            f"Trader decision: {decision.get('action')} {decision.get('symbol')}\n"
            f"Risk approved: {'YES' if approved else 'NO — must HOLD'}\n"
            f"Risk synthesis: {state.get('risk_synthesis', '')}\n"
            f"Max simultaneous positions: {max_positions}\n\n"
            "Make the final call. Remember: if verdict is HOLD or risk not approved, you MUST HOLD."
        )),
    ])

    text = response.content

    # ── Programmatic guardrails (freno asimétrico) ──
    if not approved:
        pm = {"action": "HOLD", "symbol": "NONE", "size_usd": 0.0,
              "rationale": f"REJECTED by risk guardrails. Original response:\n{text}"}
        return {
            "pm_decision": pm,
            "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
        }

    if verdict == "HOLD":
        pm = {"action": "HOLD", "symbol": "NONE", "size_usd": 0.0,
              "rationale": f"Debate verdict was HOLD — PM cannot originate. Original:\n{text}"}
        return {
            "pm_decision": pm,
            "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
        }

    # Parse LLM response — clamp to within guardrails
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

    # Clamp: PM can reduce but never increase trader's proposed size
    trader_symbol = decision.get("symbol", "NONE")
    if pm["symbol"] != trader_symbol and trader_symbol != "NONE":
        pm["symbol"] = trader_symbol

    return {
        "pm_decision": pm,
        "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
    }
