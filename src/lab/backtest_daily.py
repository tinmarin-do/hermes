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

v3 (enmienda §9.3, trials 9+): `stop_loss` — si el low del día siguiente toca
entrada×(1−sl), la pata sale a −sl + fee extra. Fill al nivel del stop (cripto 24/7,
sin gaps overnight; velas 1h subyacentes). Ambigüedad de path low/high el mismo día:
PESIMISTA, el stop dispara primero (un TP simultáneo no aplica sobre patas ya
stopeadas). El TP-3% quedó ENTERRADO con evidencia (EXPERIMENT_LOG 2026-07-12) —
el parámetro se conserva solo por reproducibilidad de los trials 1-8. Métrica nueva:
`profit_factor` = Σ días ganadores / |Σ días perdedores| (meta v2: ≥ 1.5).

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
    take_profit: float | None = None  # ENTERRADO (solo reproducibilidad trials 1-8)
    smooth_alpha: float | None = None  # α de ejecución suavizada (None ≡ 1.0)
    stop_loss: float | None = None  # ENTERRADO (solo reproducibilidad trials 9-12)
    # H12: cadencia del rebalanceo = horizonte del label (REGLA EN PIEDRA §3 del
    # pre-registro). signals debe traer SOLO fechas de rebalanceo y fwd_ret del
    # horizonte; anualización y mínimo de observaciones escalan con H.
    horizon_days: int = 1


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
        exit_fee_extra = 0.0
        exit_leg = params.fee_rate + params.slippage
        if len(w) and (params.stop_loss is not None or params.take_profit is not None):
            ret = ret.copy()
            held = day.index.intersection(w.index)
            stopped = pd.Index([])
            if params.stop_loss is not None:
                hit = day.loc[held, "fwd_low_ret"] <= -params.stop_loss
                stopped = hit[hit].index
                ret[stopped] = -params.stop_loss
                exit_fee_extra += float(exit_leg * w.reindex(stopped).fillna(0).sum())
            if params.take_profit is not None:
                hit = day.loc[held, "fwd_high_ret"] >= params.take_profit
                # pesimista (§9.3): el stop dispara primero — sin TP sobre patas stopeadas
                tp_idx = hit[hit].index.difference(stopped)
                ret[tp_idx] = params.take_profit
                exit_fee_extra += float(exit_leg * w.reindex(tp_idx).fillna(0).sum())

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
        cost = (params.fee_rate + params.slippage) * turnover + exit_fee_extra
        daily_net.append(gross - cost)
        turnover_hist.append(turnover)
        prev_w = w

    r = np.asarray(daily_net)
    h = params.horizon_days
    min_obs = 30 if h == 1 else (20 if h <= 14 else 10)  # §10: H>14 → phase-mean manda
    if len(r) < min_obs:
        return {"error": f"menos de {min_obs} periodos de validación", "days": len(r)}
    # benchmark: equal-weight buy&hold aprox (entrada única con fee; sin rebalanceo)
    b = np.asarray(daily_bench)
    b[0] -= params.fee_rate + params.slippage
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    ppy = PPY / params.horizon_days
    sharpe = (mu / sd) * np.sqrt(ppy) if sd > 0 else 0.0
    wins, losses = float(r[r > 0].sum()), float(-r[r < 0].sum())
    profit_factor = round(wins / losses, 4) if losses > 0 else None
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
        "profit_factor": profit_factor,
        "net_series": [round(float(x), 6) for x in r],
        "avg_turnover": round(float(np.mean(turnover_hist)), 4),
        "benchmark_ew_daily_pct": round(float(b.mean()) * 100, 4),
        "excess_vs_ew_pct": round((mu - float(b.mean())) * 100, 4),
        "take_profit": params.take_profit,
        "stop_loss": params.stop_loss,
        "threshold": params.threshold,
        "top_k": params.top_k,
        "smooth_alpha": params.smooth_alpha,
        "horizon_days": params.horizon_days,
    }
