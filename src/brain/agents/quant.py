"""Quant core node — runs LightGBM predictor as first decision step in the graph.

§8.7.2: régimen → LightGBM (dirección) → GARCH (sizing) → tesis cuant [DETERMINISTA].
This node runs BEFORE any LLM agent. Its output is the maximum trade — agents can only
reduce or veto, never originate or amplify.
"""
import os
from pathlib import Path

from src.brain.state import HermesState


def quant_core_node(state: HermesState) -> dict:
    """Compute quant_signal from gold_signals using LightGBM (or heuristic fallback).

    Produces {direction, confidence, size_usd, symbol, rationale} — agents can only
    clamp down from here, never originate.
    """
    signals = state.get("gold_signals", [])
    if not signals:
        return {"quant_signal": _hold("No gold signals available")}

    kelly_frac = float(os.environ.get("HERMES_KELLY_FRACTION", "0.10"))

    from src.brain.quant_core import QuantCore
    model_path = Path("data/models/quant_core_lgbm.pkl")
    if model_path.exists():
        core = QuantCore.load(model_path)
    else:
        core = QuantCore()

    owned_symbols = state.get("symbols", [])
    best_signal = None
    best_conf = -1.0
    for sig in signals:
        sym = sig.get("symbol", "")
        if sym not in owned_symbols:
            continue
        qs = core.predict(sig, kelly_fraction=kelly_frac)
        if qs.direction != "HOLD" and qs.confidence > best_conf:
            best_conf = qs.confidence
            best_signal = {
                "direction": qs.direction,
                "confidence": qs.confidence,
                "size_usd": qs.size_usd,
                "symbol": qs.symbol,
                "rationale": (
                    f"QuantCore (LightGBM): P={qs.raw_probability:.3f} → {qs.direction} "
                    f"(conf={qs.confidence:.3f}). Kelly size=${qs.size_usd:.2f} "
                    f"(frac={kelly_frac}, GARCH vol)."
                ),
            }

    if best_signal is None:
        return {"quant_signal": _hold("QuantCore: no actionable signals")}

    return {"quant_signal": best_signal}


def _hold(reason: str) -> dict:
    return {
        "direction": "HOLD",
        "confidence": 0.0,
        "size_usd": 0.0,
        "symbol": "NONE",
        "rationale": reason,
    }
