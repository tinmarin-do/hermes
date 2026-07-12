"""Backtest diario MXN del arco H11 (Fase F) — motor ligero, fees sobre TURNOVER.

Probabilidades → cartera long-only diaria: filtro p > umbral, top-k por p,
pesos ∝ p / rv_20d (conf × inverse-vol, la fórmula del allocator, mínima).
Fees + slippage se cobran sobre el turnover Σ|Δw| (NO sobre exposición bruta:
a cadencia diaria eso cobraría 72bps/día fijos y mataría todo artificialmente).

Variante TP-3% (decisión #10, SIEMPRE se corre junto a la base): si el high del
día siguiente toca entrada×(1+tp), el retorno de esa pata se corta en +tp y se
cobra una pata extra de fee (la venta anticipada; la recompra la captura el
turnover del día siguiente).

v2 (trials 6+): `smooth_alpha` — ejecución suavizada w_exec = α·target + (1−α)·w_prev
(α=1 ≡ sin suavizado). Hipótesis: los trials 1-5 mostraron bruto ~+0.3%/día con el
umbral bajo, aniquilado por turnover 1.2-1.4/día × 46bps; suavizar corta el costo
sin tocar la señal. Posiciones <0.5% se liquidan (polvo). Además cada backtest
reporta el benchmark buy&hold equal-weight del mismo periodo (entrada única con fee)
— el control que separa alpha del modelo vs beta del mercado en el holdout.

Todo en MXN · PPY=365 · PSR/DSR importados puros de src.brain.backtest.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.brain.backtest import deflated_sharpe, psr

PPY = 365
FEE_RATE = 0.0036  # Bitso taker
SLIPPAGE = 0.0010  # sensibilidad por liquidez del venue


MIN_WEIGHT = 0.005  # posiciones suavizadas por debajo se liquidan (polvo)


@dataclass
class StrategyParams:
    threshold: float = 0.5
    top_k: int = 5
    fee_rate: float = FEE_RATE
    slippage: float = SLIPPAGE
    take_profit: float | None = None  # 0.03 → variante TP-3%
    smooth_alpha: float | None = None  # α de ejecución suavizada (None ≡ 1.0)


def _weights_for_day(day: pd.DataFrame, p: StrategyParams) -> pd.Series:
    """p>umbral, top-k por probabilidad, w ∝ p/rv normalizado (Σw ≤ 1).

    `day` viene indexado por symbol; el resultado hereda ese índice.
    """
    sel = day[day["p"] > p.threshold].nlargest(p.top_k, "p")
    if sel.empty:
        return pd.Series(dtype=float)
    raw = sel["p"] / sel["rv_20d"].clip(lower=1e-4)
    return raw / raw.sum()


def run_backtest(
    signals: pd.DataFrame, params: StrategyParams, n_trials: int = 1
) -> dict[str, Any]:
    """signals: (ts, symbol, p, rv_20d, fwd_ret_24h_mxn, fwd_high_ret) por día de validación.

    fwd_ret_24h_mxn = retorno close→close del día siguiente (MXN).
    fwd_high_ret = retorno close→HIGH del día siguiente (MXN) — dispara el TP.
    """
    signals = signals.sort_values(["ts", "symbol"])
    daily_net: list[float] = []
    daily_bench: list[float] = []
    turnover_hist: list[float] = []
    prev_w = pd.Series(dtype=float)

    for _, day in signals.groupby("ts", sort=True):
        day = day.set_index("symbol")
        w = _weights_for_day(day, params)

        if params.smooth_alpha is not None:
            idx = prev_w.index.union(w.index)
            w = params.smooth_alpha * w.reindex(idx).fillna(0) + (
                1 - params.smooth_alpha
            ) * prev_w.reindex(idx).fillna(0)
            w = w[w >= MIN_WEIGHT]

        ret = day["fwd_ret_24h_mxn"]
        tp_fee_extra = 0.0
        if params.take_profit is not None and len(w):
            hit = day.loc[day.index.intersection(w.index), "fwd_high_ret"] >= params.take_profit
            capped = ret.copy()
            capped[hit[hit].index] = params.take_profit
            ret = capped
            tp_fee_extra = float(
                (params.fee_rate + params.slippage) * w.reindex(hit[hit].index).fillna(0).sum()
            )

        # símbolo retenido sin fila hoy (hueco de data) → se asume plano
        gross = float((w * ret.reindex(w.index).fillna(0.0)).sum()) if len(w) else 0.0
        daily_bench.append(float(day["fwd_ret_24h_mxn"].mean()))
        turnover = float(
            (
                w.reindex(prev_w.index.union(w.index)).fillna(0)
                - prev_w.reindex(prev_w.index.union(w.index)).fillna(0)
            )
            .abs()
            .sum()
        )
        cost = (params.fee_rate + params.slippage) * turnover + tp_fee_extra
        daily_net.append(gross - cost)
        turnover_hist.append(turnover)
        prev_w = w

    r = np.asarray(daily_net)
    if len(r) < 30:
        return {"error": "menos de 30 días de validación", "days": len(r)}
    # benchmark: equal-weight buy&hold aprox (entrada única con fee; sin rebalanceo)
    b = np.asarray(daily_bench)
    b[0] -= params.fee_rate + params.slippage
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    sharpe = (mu / sd) * np.sqrt(PPY) if sd > 0 else 0.0
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(equity)
    maxdd = float(((equity - peak) / peak).min())
    return {
        "days": int(len(r)),
        "mean_daily_net_pct": round(mu * 100, 4),
        "total_return_pct": round((equity[-1] - 1) * 100, 2),
        "sharpe_ann": round(float(sharpe), 3),
        "psr_0": round(float(psr(r.tolist(), sr_benchmark=0.0)), 4),
        "dsr": round(float(deflated_sharpe(r.tolist(), n_trials=max(n_trials, 1))), 4),
        "max_drawdown_pct": round(maxdd * 100, 2),
        "hit_rate": round(float((r > 0).mean()), 4),
        "avg_turnover": round(float(np.mean(turnover_hist)), 4),
        "benchmark_ew_daily_pct": round(float(b.mean()) * 100, 4),
        "excess_vs_ew_pct": round((mu - float(b.mean())) * 100, 4),
        "take_profit": params.take_profit,
        "threshold": params.threshold,
        "top_k": params.top_k,
        "smooth_alpha": params.smooth_alpha,
    }
