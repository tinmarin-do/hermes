"""Trader — synthesizes quant_signal + debate verdict into a clamped decision.

§8.7.2 brake semantics:
- Goes last in the pipeline (has access to quant_signal and debate verdict)
- Quant fixes direction and max size; debate multiplier ∈ [0, 1]
- Trader can RECUSE (HOLD) or CONFIRM (same direction, clamped size)
- Trader NEVER flips direction or amplifies size beyond quant.
"""
import os

from langchain_core.messages import HumanMessage, SystemMessage

from src.brain.llm import get_llm
from src.brain.state import HermesState

SYSTEM = """You are a crypto trader at an algorithmic trading firm.
You receive a QUANT THESIS (from a LightGBM model — deterministic direction and size)
and a DEBATE VERDICT (from bull/bear researchers — qualitative red-team).

Your job:
1. Evaluate whether the debate SUPPORTS, WEAKENS, or VETOES the quant thesis.
2. NEVER flip direction — the quant thesis sets direction, you can only confirm or hold.
3. NEVER increase size beyond the quant maximum — you can only hold or reduce.
4. If the debate verdict is HOLD, you MUST HOLD.

Respond in this format:
ACTION: <BUY|SELL|HOLD>
SYMBOL: <symbol or NONE>
RATIONALE: <2-3 sentences explaining how the debate affects the quant thesis>"""


def _debate_multiplier(debate_verdict: str, quant_direction: str,
                       debate_confidence: float) -> float:
    """Compute multiplier from debate vs quant thesis agreement.

    If debate_verdict matches quant_direction → multiplier = debate_confidence.
    If debate_verdict == HOLD → 0 (veto).
    If debate_verdict disagrees → 0 (veto — debate can't flip direction).
    """
    if debate_verdict == "HOLD":
        return 0.0
    if debate_verdict == quant_direction:
        return debate_confidence
    return 0.0


def trader(state: HermesState) -> dict:
    llm = get_llm("decision")
    quant = state.get("quant_signal", {})
    verdict = state.get("debate_verdict", "HOLD")
    debate_conf = state.get("debate_confidence", 0.5)
    allowed = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")

    quant_dir = quant.get("direction", "HOLD")
    quant_size = quant.get("size_usd", 0.0)
    quant_symbol = quant.get("symbol", "NONE")
    quant_rationale = quant.get("rationale", "")

    multiplier = _debate_multiplier(verdict, quant_dir, debate_conf)

    reports_text = "\n".join(
        f"- {r['symbol']}: {r['bias']} — {r['analysis'][:200]}"
        for r in state.get("analyst_reports", [])
    )

    response = llm.invoke([
        SystemMessage(content=SYSTEM),
        HumanMessage(content=(
            f"QUANT THESIS (deterministic, max allowed):\n"
            f"  Direction: {quant_dir}\n"
            f"  Max size: ${quant_size:.2f}\n"
            f"  Symbol: {quant_symbol}\n"
            f"  Basis: {quant_rationale}\n\n"
            f"DEBATE VERDICT (qualitative red-team):\n"
            f"  Verdict: {verdict} (confidence: {debate_conf:.0%})\n"
            f"  Multiplier: {multiplier:.2f} ×\n\n"
            f"Regime: {state.get('regime_summary', '')}\n"
            f"Analyst reports:\n{reports_text}\n"
            f"Allowed symbols: {allowed}\n\n"
            f"Make your adjusted trading decision. Remember: you can CONFIRM or "
            f"HOLD, never flip direction or increase size."
        )),
    ])

    text = response.content

    # ── Programmatic brake enforcement ──
    if multiplier == 0.0 or quant_dir == "HOLD":
        decision = {
            "action": "HOLD",
            "symbol": "NONE",
            "size_usd": 0.0,
            "rationale": (
                f"Debate vetoed quant thesis ({verdict} vs {quant_dir}) "
                f"— trader brake engaged. Original response:\n{text}"
            ),
        }
    else:
        action = quant_dir  # never flip
        symbol = quant_symbol
        size = quant_size * multiplier

        # Parse LLM's intent (for rationale enrichment only)
        for line in text.splitlines():
            if line.startswith("ACTION:"):
                parsed = line.split(":", 1)[1].strip()
                if parsed in ("BUY", "SELL"):
                    pass  # direction is fixed by quant
                elif parsed == "HOLD":
                    action = "HOLD"
                    size = 0.0

        decision = {
            "action": action,
            "symbol": symbol,
            "size_usd": round(size, 2),
            "rationale": (
                f"[Trader] quant={quant_dir} ${quant_size:.2f} × "
                f"debate_multiplier={multiplier:.2f} → "
                f"{action} ${size:.2f}\n{text}"
            ),
        }

    return {
        "trader_decision": decision,
        "messages": [HumanMessage(content=f"[Trader]\n{text}")],
    }
