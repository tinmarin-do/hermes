"""Quant core node — runs LightGBM predictor as first decision step in the graph.

§8.7.2: régimen → LightGBM (dirección) → GARCH (sizing) → tesis cuant [DETERMINISTA].
This node runs BEFORE any LLM agent. Its output is the maximum trade — agents can only
reduce or veto, never originate or amplify.

§8.8: emits a per-symbol signal vector (`quant_signals`) for the portfolio allocator, plus
the single best signal (`quant_signal`) that the debate/trader/PM red-team as the lead thesis.
"""

import os
from pathlib import Path
from typing import Any

from src.brain.state import HermesState

# Short es la operación más riesgosa → exige más evidencia que un long (§8.8).
# P ≤ 0.25 ya implica confianza ≥ 0.50; este piso es el guardia explícito para el
# camino heurístico (sin modelo) y para dejar la intención visible.
SHORT_MIN_CONF = 0.50


def _short_confirmed(sig: dict[str, Any]) -> bool:
    """Confirmación de régimen bajista para habilitar un short (ultra-conservador).

    Exige tendencia persistente a la baja (Hurst ≥ 0.50, no mean-reversion) + drift
    negativo a 24h. Si falta cualquiera de los dos → no se confirma (se degrada a HOLD).
    """
    f = sig.get("features", {})
    hurst = f.get("hurst")
    ret_24h = f.get("returns_24h")
    if hurst is None or ret_24h is None:
        return False
    return hurst >= 0.50 and ret_24h < 0


def quant_core_node(state: HermesState) -> dict:
    """Compute per-symbol quant signals + the best single signal.

    Produces `quant_signals` (vector for the allocator) and `quant_signal` (lead thesis).
    Agents can only clamp down from here, never originate. Shorts are gated by an
    asymmetric threshold (P ≤ 0.25) plus bearish-regime confirmation (§8.8).
    """
    signals = state.get("gold_signals", [])
    if not signals:
        return {"quant_signals": [], "quant_signal": _hold("No gold signals available")}

    kelly_frac = float(os.environ.get("HERMES_KELLY_FRACTION", "0.10"))

    from src.brain.quant_core import QuantCore

    model_path = Path("data/models/quant_core_lgbm.pkl")
    core = QuantCore.load(model_path) if model_path.exists() else QuantCore()

    owned_symbols = state.get("symbols", [])
    quant_signals: list[dict] = []
    best_signal: dict | None = None
    best_conf = -1.0

    for sig in signals:
        sym = sig.get("symbol", "")
        if sym not in owned_symbols:
            continue

        qs = core.predict(sig, kelly_fraction=kelly_frac)
        direction = qs.direction
        confidence = qs.confidence

        # ── Short ultra-conservador (§8.8): gate por confianza + régimen bajista ──
        if direction == "SELL":
            if confidence < SHORT_MIN_CONF or not _short_confirmed(sig):
                direction, confidence = "HOLD", 0.0

        garch_vol = (sig.get("features", {}).get("garch_vol")) or 0.0
        entry = {
            "symbol": sym,
            "direction": direction,
            "confidence": confidence,
            "size_usd": qs.size_usd if direction != "HOLD" else 0.0,
            "raw_probability": qs.raw_probability,
            "garch_vol": garch_vol,
            "regime": sig.get("regime", "volatile"),
            "rationale": (
                f"QuantCore: P={qs.raw_probability:.3f} → {direction} "
                f"(conf={confidence:.3f}, GARCH vol={garch_vol:.5f})."
            ),
        }
        quant_signals.append(entry)

        if direction != "HOLD" and confidence > best_conf:
            best_conf = confidence
            best_signal = {
                "direction": direction,
                "confidence": confidence,
                "size_usd": entry["size_usd"],
                "symbol": sym,
                "rationale": entry["rationale"],
            }

    if best_signal is None:
        best_signal = _hold("QuantCore: no actionable signals")

    return {"quant_signals": quant_signals, "quant_signal": best_signal}


def _hold(reason: str) -> dict:
    return {
        "direction": "HOLD",
        "confidence": 0.0,
        "size_usd": 0.0,
        "symbol": "NONE",
        "rationale": reason,
    }
