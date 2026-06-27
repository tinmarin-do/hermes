"""Portfolio Manager — final decision gate."""
import os
from langchain_core.messages import HumanMessage, SystemMessage
from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are the Portfolio Manager. You have the final word on every trade.
You receive the trader's decision, the risk team's synthesis, and approval status.
If risk is NOT approved, you must HOLD — no exceptions.
If risk IS approved, you may confirm or reduce the trade.

Always respond in this exact format:
FINAL_ACTION: <BUY|SELL|HOLD>
FINAL_SYMBOL: <symbol or NONE>
FINAL_SIZE_USD: <number>
RATIONALE: <2-3 sentences>"""


def portfolio_manager(state: HermesState) -> dict:
    llm = get_llm("decision")
    decision = state.get("trader_decision", {})
    approved = state.get("risk_approved", False)
    max_positions = int(os.environ.get("HERMES_MAX_POSITIONS", "2"))

    response = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"Trader decision: {decision.get('action')} {decision.get('symbol')}\n"
            f"Risk approved: {'YES' if approved else 'NO — must HOLD'}\n"
            f"Risk synthesis: {state.get('risk_synthesis', '')}\n"
            f"Max simultaneous positions: {max_positions}\n\n"
            "Make the final call."
        )),
    ])

    text = response.content
    pm = {"action": "HOLD", "symbol": "NONE", "size_usd": 0.0, "rationale": text}

    for line in text.splitlines():
        if line.startswith("FINAL_ACTION:"):
            pm["action"] = line.split(":", 1)[1].strip()
        elif line.startswith("FINAL_SYMBOL:"):
            pm["symbol"] = line.split(":", 1)[1].strip()
        elif line.startswith("FINAL_SIZE_USD:"):
            try:
                pm["size_usd"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    return {
        "pm_decision": pm,
        "messages": [HumanMessage(content=f"[PortfolioManager]\n{text}")],
    }
