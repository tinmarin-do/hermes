"""Entry point for one pipeline run."""
import uuid
import json
import os
from src.brain.graph import hermes_graph
from src.data.gold.aggregate import aggregate


def run(symbols: list[str] | None = None, timeframe: str = "1h") -> dict:
    if symbols is None:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    gold_signals = aggregate(symbols, timeframe)
    if not gold_signals:
        raise RuntimeError("No Gold signals available — run data:aggregate-gold first")

    initial_state: dict = {
        "run_id": str(uuid.uuid4()),
        "symbols": symbols,
        "timeframe": timeframe,
        "gold_signals": gold_signals,
        "regime_summary": "",
        "analyst_reports": [],
        "bull_argument": "",
        "bear_argument": "",
        "debate_rounds": [],
        "debate_round_count": 0,
        "debate_verdict": "HOLD",
        "debate_confidence": 0.5,
        "trader_decision": {},
        "risk_reports": [],
        "risk_synthesis": "",
        "risk_approved": False,
        "pm_decision": {},
        "messages": [],
    }

    # Stream node-by-node for visibility (Ollama local es lento; .invoke() era una
    # caja negra). "updates" da el nombre del nodo + delta; "values" da el estado
    # acumulado completo, cuyo último valor es el estado final.
    print(f"[runner] streaming · run_id={initial_state['run_id']} · symbols={symbols}", flush=True)
    final_state: dict = initial_state
    for mode, chunk in hermes_graph.stream(initial_state, stream_mode=["updates", "values"]):
        if mode == "updates":
            for node, update in (chunk or {}).items():
                detail = ""
                if update:
                    if "debate_round_count" in update:
                        detail = f" · round={update['debate_round_count']}"
                    elif "debate_verdict" in update:
                        detail = f" · verdict={update['debate_verdict']} conf={update.get('debate_confidence')}"
                    elif "trader_decision" in update:
                        detail = f" · action={update['trader_decision'].get('action')}"
                    elif "risk_approved" in update:
                        detail = f" · approved={update['risk_approved']}"
                print(f"  ▸ {node}{detail}", flush=True)
        else:  # "values" → estado acumulado; el último es el final
            final_state = chunk

    pm = final_state.get("pm_decision", {})
    print(f"\n{'='*60}")
    print(f"Run ID  : {initial_state['run_id']}")
    print(f"Verdict : {final_state.get('debate_verdict')} "
          f"(conf {final_state.get('debate_confidence', 0):.0%})")
    print(f"Decision: {pm.get('action')} {pm.get('symbol')} ${pm.get('size_usd', 0):.2f}")
    print(f"Risk    : {'✅ APPROVED' if final_state.get('risk_approved') else '❌ REJECTED'}")
    print(f"{'='*60}")
    print(f"PM rationale: {pm.get('rationale', '')[:300]}")

    return final_state


if __name__ == "__main__":
    run()
