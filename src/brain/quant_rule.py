"""Regla momentum multi-escala — señal champion del núcleo cuant (PRD v0.3 §5.2/§8.6).

Única estrategia sobreviviente del arco de research H0–H8 (docs/EXPERIMENT_LOG.md):
validada en el holdout 2025-06→2026-06 como overlay DEFENSIVO — plana (+2.2%) en un
crash de −40% con la mitad del drawdown del mercado. Sin ML, sin parámetros tuneados,
$0 por inferencia.

Mecánica (H6): cada escala vota +1/−1 según el signo de su retorno trailing; la
dirección es el signo de la suma y la confianza `|votos| / escalas válidas`
(unanimidad → máxima). El desacuerdo entre escalas degrada a HOLD — robustez por
construcción, sin magnitudes que tunear.

El contrato de salida es el mismo `QuantSignal` del núcleo (§8.7.2): los agentes LLM
solo pueden frenar lo que esta regla origina. El LightGBM falsificado corre aparte en
shadow mode (`src/brain/shadow.py`) sin ejecutar órdenes.
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime, timedelta
from typing import Any

from src.brain.quant_core import QuantSignal, _kelly_size

# 7d / 14d / 30d / 90d en velas 1h — fijas a priori (H6). NO tunear (§8.9): el
# single-30d rendía más en iteración pero era suerte de parámetro (H5-stress).
MULTISCALE_LOOKBACKS = (168, 336, 720, 2160)

CONF_CAP = 0.95  # mismo techo que el resto del stack


def vote_from_returns(past_returns: list[float | None]) -> tuple[str, float]:
    """Voto de signo multi-escala → (direction, confidence). Pura, sin I/O.

    Escalas sin dato no votan. Suma nula (desacuerdo o sin datos) → HOLD.
    """
    votes = 0
    valid = 0
    for pr in past_returns:
        if pr is None:
            continue
        valid += 1
        votes += 1 if pr > 0 else (-1 if pr < 0 else 0)
    if valid == 0 or votes == 0:
        return "HOLD", 0.0
    conf = round(min(abs(votes) / valid, CONF_CAP), 4)
    return ("BUY" if votes > 0 else "SELL"), conf


def probability_from(direction: str, confidence: float) -> float:
    """Mapea (direction, confidence) al espacio P del contrato del grafo.

    Inversa de `_prob_to_signal` (conf = |P−0.5|×2). Preserva la equivalencia
    asimétrica del short: conf ≥ 0.50 ⟺ P ≤ 0.25 (§8.8).
    """
    if direction == "BUY":
        return round(0.5 + confidence / 2, 4)
    if direction == "SELL":
        return round(0.5 - confidence / 2, 4)
    return 0.5


def _past_returns(
    symbol: str,
    timeframe: str,
    asof: datetime,
    lookbacks: tuple[int, ...] = MULTISCALE_LOOKBACKS,
) -> list[float | None]:
    """Retornos trailing as-of `asof` para cada lookback, desde bronze (una query)."""
    from src.data.db import get_connection

    # bronze ts son naive-UTC; normalizar el stamp para comparar (fix tz de H8).
    if asof.tzinfo is not None:
        asof = asof.replace(tzinfo=None)

    con = get_connection()
    try:
        rows = con.execute(
            "SELECT ts, close FROM bronze_ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
            [symbol, timeframe],
        ).fetchall()
    finally:
        con.close()
    ts_list = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]

    def _asof_close(target: datetime) -> float | None:
        i = bisect.bisect_right(ts_list, target) - 1
        return closes[i] if i >= 0 else None

    now = _asof_close(asof)
    out: list[float | None] = []
    for lb in lookbacks:
        then = _asof_close(asof - timedelta(hours=lb))
        out.append(now / then - 1.0 if now and then else None)
    return out


def multiscale_signal(gold_signal: dict[str, Any], kelly_fraction: float = 0.10) -> QuantSignal:
    """Señal champion para un símbolo, as-of el ts de su gold signal."""
    sym = gold_signal.get("symbol", "UNKNOWN")
    timeframe = gold_signal.get("timeframe", "1h")
    ts_str = gold_signal.get("ts", "")
    asof = (
        datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts_str
        else datetime.now(UTC).replace(tzinfo=None)
    )

    rets = _past_returns(sym, timeframe, asof)
    direction, confidence = vote_from_returns(rets)

    garch_vol = gold_signal.get("features", {}).get("garch_vol") or 0.0
    size_usd = _kelly_size(confidence, kelly_fraction, garch_vol) if direction != "HOLD" else 0.0

    return QuantSignal(
        symbol=sym,
        direction=direction,
        confidence=confidence,
        raw_probability=probability_from(direction, confidence),
        size_usd=size_usd,
        features_used={
            f"mom_{lb}h": round(r, 6)
            for lb, r in zip(MULTISCALE_LOOKBACKS, rets, strict=True)
            if r is not None
        },
        model_version="multimom-h6",
    )
