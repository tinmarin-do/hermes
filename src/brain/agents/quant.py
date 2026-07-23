"""Quant core node — regla momentum multi-escala como señal champion (PRD v0.3).

§8.7.2: régimen → regla multi-escala (dirección) → GARCH (sizing) → tesis cuant
[DETERMINISTA]. Este nodo corre ANTES de cualquier agente LLM. Su salida es el trade
máximo — los agentes solo pueden recortar o vetar, nunca originar ni amplificar.

§8.8: emite el vector por símbolo (`quant_signals`) para el allocator, más la mejor
señal individual (`quant_signal`) que el debate/trader/PM red-teamean como tesis líder.

Shadow (§5.2/§8.9): el LightGBM — falsificado como decisor (EXPERIMENT_LOG Exp. 0:
PSR 0.504 en 5.5 años) — sigue corriendo por corrida como challenger placeholder;
sus señales van a `shadow_signals` (persistidas por el runner) y JAMÁS ejecutan.
"""

import os
from pathlib import Path
from typing import Any

from src.brain.state import HermesState

# Short es la operación más riesgosa → exige más evidencia que un long (§8.8).
# conf ≥ 0.50 ⟺ P ≤ 0.25; este piso deja la intención explícita en el nodo.
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
    """Compute per-symbol quant signals (champion) + shadow signals + best single.

    Champion = regla momentum multi-escala (`quant_rule`). Shorts gated por umbral
    asimétrico + confirmación de régimen bajista (§8.8). El shadow (LightGBM/heurística)
    se computa sobre los mismos gold signals para el registro comparativo — no decide.
    """
    signals = state.get("gold_signals", [])
    if not signals:
        return {
            "quant_signals": [],
            "shadow_signals": [],
            "quant_signal": _hold("No gold signals available"),
        }

    kelly_frac = float(os.environ.get("HERMES_KELLY_FRACTION", "0.10"))

    from src.brain.quant_core import QuantCore
    from src.brain.quant_rule import multiscale_signal

    model_path = Path("data/models/quant_core_lgbm.pkl")
    shadow_core = QuantCore.load(model_path) if model_path.exists() else QuantCore()
    shadow_model = "lightgbm" if model_path.exists() else "heuristic-5f"

    owned_symbols = state.get("symbols", [])
    quant_signals: list[dict] = []
    shadow_signals: list[dict] = []
    best_signal: dict | None = None
    best_conf = -1.0

    for sig in signals:
        sym = sig.get("symbol", "")
        if sym not in owned_symbols:
            continue

        qs = multiscale_signal(sig, kelly_fraction=kelly_frac)
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
                f"QuantRule multimom 7/14/30/90d: P={qs.raw_probability:.3f} → {direction} "
                f"(conf={confidence:.3f}, GARCH vol={garch_vol:.5f})."
            ),
        }
        quant_signals.append(entry)

        # ── Shadow challenger (no ejecuta): señal cruda del LightGBM/heurística ──
        ss = shadow_core.predict(sig, kelly_fraction=kelly_frac)
        shadow_signals.append(
            {
                "model": shadow_model,
                "symbol": sym,
                "direction": ss.direction,
                "confidence": ss.confidence,
                "raw_probability": ss.raw_probability,
                "size_usd": ss.size_usd,
            }
        )

        if direction != "HOLD" and confidence > best_conf:
            best_conf = confidence
            best_signal = {
                "direction": direction,
                "confidence": confidence,
                "size_usd": entry["size_usd"],
                "symbol": sym,
                "rationale": entry["rationale"],
            }

    # ── Shadow vol-target (capa de RIESGO, decisión producto 2026-07-07): variante
    # del campeón con exposición escalada a σ-objetivo. No decide; nunca rompe el run.
    try:
        from src.brain.voltarget import voltarget_shadow

        shadow_signals.extend(voltarget_shadow(quant_signals))
    except Exception as exc:  # noqa: S110 — shadow jamás tumba al campeón
        print(f"[voltarget] shadow no disponible (no crítico): {exc}", flush=True)

    if best_signal is None:
        best_signal = _hold("QuantRule: no actionable signals")

    return {
        "quant_signals": quant_signals,
        "shadow_signals": shadow_signals,
        "quant_signal": best_signal,
    }


def _hold(reason: str) -> dict:
    return {
        "direction": "HOLD",
        "confidence": 0.0,
        "size_usd": 0.0,
        "symbol": "NONE",
        "rationale": reason,
    }
