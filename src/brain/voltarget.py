"""Vol-targeting shadow — variante del campeón como capa de RIESGO (H10.3).

Decisión de PRODUCTO de Erika (2026-07-07, DESIGN_H10 enmienda): el overlay de
vol-targeting NO promovió como alpha (DSR 0.53, pierde años alcistas por diseño —
EXPERIMENT_LOG lección #20), pero SÍ mostró perfil de riesgo superior (maxDD −40%
vs −62%, vol −40%). Corre en shadow como variante del campeón — misma señal, misma
dirección, exposición escalada — y el juez es el track record forward (§8.9 v2).
JAMÁS ejecuta; si en N meses la curva shadow confirma el perfil, se considera para
live como guardrail con su propio proceso.

Mecánica (idéntica a research/h10/h10_3_voltarget.py, parámetros FIJOS a priori):
EWMA RiskMetrics λ=0.94 sobre los retornos DIARIOS de la curva oficial de equity
(1 punto/día, §8.9 — el libro del campeón ES el equity live). σ_target = 25% anual.
Exposición m_t = min(1, σ_target/σ_forecast); warmup 20 retornos con m=1. Solo usa
retornos hasta ayer — sin look-ahead por construcción.

Persistencia: filas en shadow_signals con model='champion-voltarget25'. El campo
raw_probability lleva m_t (documentado aquí y en shadow.py): cada fila es
auto-descriptiva y el evaluador forward reconstruye el libro escalado sin joins.
"""

from __future__ import annotations

import math
from typing import Any

LAMBDA = 0.94  # RiskMetrics
SIGMA_TARGET = 0.25  # anual, fijo a priori (pre-registro H10.3)
WARMUP = 20  # retornos diarios; con menos historia m=1
PPY = 365
MODEL_NAME = "champion-voltarget25"


def exposure_from_returns(rets: list[float]) -> dict[str, Any]:
    """m_t de HOY dado el historial de retornos diarios (el último es el de ayer).

    Réplica exacta del pass 2 de research: v se inicializa con la varianza de los
    primeros WARMUP retornos y se actualiza con cada retorno posterior, incluido
    el último cerrado. Devuelve {"m", "sigma_ann", "n_rets"}.
    """
    n = len(rets)
    if n < WARMUP:
        return {"m": 1.0, "sigma_ann": None, "n_rets": n}
    mean = sum(rets[:WARMUP]) / WARMUP
    v = sum((r - mean) ** 2 for r in rets[:WARMUP]) / WARMUP
    for r in rets[WARMUP - 1 :]:
        v = LAMBDA * v + (1 - LAMBDA) * r * r
    sigma_ann = math.sqrt(max(v, 1e-12) * PPY)
    return {
        "m": round(min(1.0, SIGMA_TARGET / sigma_ann), 4),
        "sigma_ann": round(sigma_ann, 4),
        "n_rets": n,
    }


def current_exposure() -> dict[str, Any]:
    """m_t desde la curva oficial de equity (último punto por día UTC, como §8.9).

    Sin tabla / sin historia suficiente → m=1 (comportamiento de warmup, no error).
    """
    from src.data.db import get_connection

    con = get_connection()
    try:
        series = con.execute(
            """SELECT equity FROM (
                   SELECT ts, equity,
                          ROW_NUMBER() OVER (PARTITION BY CAST(ts AS DATE)
                                             ORDER BY ts DESC) AS rn
                   FROM equity_curve) WHERE rn = 1 ORDER BY ts"""
        ).fetchall()
    except Exception:
        return {"m": 1.0, "sigma_ann": None, "n_rets": 0}
    finally:
        con.close()

    equities = [float(r[0]) for r in series if r[0]]
    rets = [
        equities[i] / equities[i - 1] - 1.0 for i in range(1, len(equities)) if equities[i - 1] > 0
    ]
    return exposure_from_returns(rets)


def voltarget_shadow(quant_signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filas shadow de la variante vol-target: campeón × m_t (dirección intacta).

    raw_probability = m_t (exposición del día — ver docstring del módulo).
    """
    if not quant_signals:
        return []
    exp = current_exposure()
    m = exp["m"]
    return [
        {
            "model": MODEL_NAME,
            "symbol": s["symbol"],
            "direction": s["direction"],
            "confidence": s.get("confidence"),
            "raw_probability": m,
            "size_usd": round((s.get("size_usd") or 0.0) * m, 6),
        }
        for s in quant_signals
    ]
