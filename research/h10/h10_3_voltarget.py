"""H10.3 — Vol-targeting sobre el campeón (pre-registro docs/DESIGN_H10_procesos_estocasticos.md).

Hipótesis: escalar la exposición del campeón a vol-objetivo constante (σ_target=25%
anual, FIJO a priori) mejora Sharpe y drawdown sin predecir dirección.

Mecánica (sin look-ahead):
  Pass 1: campeón H6 diario con-estado (brazo A) sin escalar → serie de retornos r_t.
  Pass 2: EWMA RiskMetrics v_t = λ·v_{t-1} + (1−λ)·r_{t-1}² (λ=0.94), inicializada con
          la varianza de los primeros 20 días (m=1 durante el warmup). Exposición
          m_t = min(1, σ_target/σ_ann_t) usa SOLO retornos hasta t−1. m_t escala los
          targets vía global_mult en el mismo evaluador con-estado (banda 5% incluida).

Criterios (los 5, fee 36bps): Sharpe > campeón brazo A · maxDD mejor · PSR(0)>0.95 ·
DSR(n=30)>0.90 · no perder vs campeón en >2 de 5 años. Diagnóstico sin DSR:
Mincer-Zarnowitz del pronóstico EWMA vs varianza realizada. Seed no aplica (determinista).
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, "/home/tea/hermes")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "h9"))

import numpy as np

from vara_h6 import (
    DB,
    PPY_DAILY,
    SYMBOLS,
    UNTIL,
    _load_garch,
    champion_signals,
    run_stateful_daily,
)

from src.brain.backtest import _iteration_stamps, deflated_sharpe, max_drawdown, psr, sharpe_ratio, _std

LAMBDA = 0.94
SIGMA_TARGET = 0.25  # anual, fijo a priori
WARMUP = 20
FEES = (0.0036, 0.0010)
N_TRIALS_DSR = 30
OUT = os.path.dirname(os.path.abspath(__file__))


def champion_returns(stamps, fee: float) -> list[float]:
    """Pass 1: reconstruye la serie diaria del campeón (mismo evaluador de la vara)."""
    res = run_stateful_daily(champion_signals, stamps, fee, return_series=True)
    return res["_daily_rets"]


def exposure_series(rets: list[float]) -> list[float]:
    """m_t con información hasta t−1 (RiskMetrics); warmup 20 días con m=1."""
    m = [1.0] * len(rets)
    if len(rets) <= WARMUP:
        return m
    v = float(np.var(rets[:WARMUP]))
    for t in range(WARMUP, len(rets)):
        v = LAMBDA * v + (1 - LAMBDA) * rets[t - 1] ** 2
        sig_ann = math.sqrt(max(v, 1e-12) * PPY_DAILY)
        m[t] = min(1.0, SIGMA_TARGET / sig_ann)
    return m


def mincer_zarnowitz(rets: list[float]) -> dict:
    """r_t² = a + b·v_t (pronóstico EWMA) — calidad del pronóstico de varianza."""
    v = float(np.var(rets[:WARMUP]))
    xs, ys = [], []
    for t in range(WARMUP, len(rets)):
        v = LAMBDA * v + (1 - LAMBDA) * rets[t - 1] ** 2
        xs.append(v)
        ys.append(rets[t] ** 2)
    x, y = np.array(xs), np.array(ys)
    b, a = np.polyfit(x, y, 1)
    r2 = float(np.corrcoef(x, y)[0, 1] ** 2)
    return {"a": float(f"{a:.3g}"), "b": round(float(b), 3), "r2": round(r2, 4), "n": len(xs)}


def main() -> None:
    os.environ.setdefault("HERMES_DUCKDB_PATH", DB)
    _load_garch()
    stamps = _iteration_stamps(SYMBOLS, "1h", "D", UNTIL)

    out: dict = {}
    for fee in FEES:
        base_rets = champion_returns(stamps, fee)
        m = exposure_series(base_rets)
        res = run_stateful_daily(
            champion_signals, stamps, fee, exposure=m, return_series=True
        )
        rets = res.pop("_daily_rets")
        res["avg_exposure"] = round(sum(m) / len(m), 4)
        res["pct_days_descaled"] = round(100 * sum(1 for x in m if x < 0.999) / len(m), 1)
        res["dsr_n30"] = round(deflated_sharpe(rets, N_TRIALS_DSR), 4)
        out[f"voltarget_fee{int(fee * 1e4)}bps"] = res
        if fee == FEES[0]:
            out["mincer_zarnowitz"] = mincer_zarnowitz(base_rets)

    with open(f"{OUT}/h10_3_results.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
