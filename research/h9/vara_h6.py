"""H9 — Paso 1: la VARA. Campeón H6 (multimom) re-corrido en ambos brazos del pre-registro.

Brazo B (7d semanal): harness existente `run_multiscale_momentum_backtest` (idéntico a H6).
Brazo A (24h diario): evaluación CON ESTADO nueva (pre-registro §3): libro persistente,
targets del allocator §8.8 con banda `min_trade_frac=0.05`, fees SOLO sobre el notional
realmente operado, mark-to-market diario, PPY=365.

$0: sin LLM, sin GCP, sin red. Seed no aplica (regla determinista). Ventana de iteración
2021-01-01 → 2025-06-28 (holdout intocado).
"""

from __future__ import annotations

import json
import math
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, "/home/tea/hermes")

import duckdb

from src.brain.agents.allocator import compute_allocations
from src.brain.backtest import (
    MULTISCALE_LOOKBACKS,
    _cached_series,
    _iteration_stamps,
    _past_return,
    _std,
    deflated_sharpe,
    max_drawdown,
    psr,
    sharpe_ratio,
)

DB = "/home/tea/hermes/data/hermes.duckdb"
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT", "AVAX/USDT", "XRP/USDT"]
UNTIL = "2025-06-28"
FEES = (0.0036, 0.0010)  # 36 bps Bitso taker (primario) · 10 bps (comparabilidad H6)
MIN_TRADE_FRAC = 0.05  # banda anti-churn de producción
PPY_DAILY = 365


# ── garch_vol as-of (una carga por símbolo, lookups en memoria) ───────────────

_GARCH: dict[str, tuple[list[datetime], list[float | None]]] = {}


def _load_garch() -> None:
    con = duckdb.connect(DB, read_only=True)
    try:
        for sym in SYMBOLS:
            rows = con.execute(
                "SELECT ts, garch_vol FROM silver_features "
                "WHERE symbol=? AND timeframe='1h' ORDER BY ts",
                [sym],
            ).fetchall()
            _GARCH[sym] = ([r[0] for r in rows], [r[1] for r in rows])
    finally:
        con.close()


def garch_asof(sym: str, ts: datetime) -> float | None:
    ts_list, vals = _GARCH[sym]
    i = bisect_right(ts_list, ts) - 1
    return float(vals[i]) if i >= 0 and vals[i] is not None else None


# ── señal del campeón H6 (idéntica a producción/backtest: voto de signos) ─────


def champion_signals(ts: datetime) -> list[dict]:
    out = []
    for sym in SYMBOLS:
        votes = valid = 0
        for lb in MULTISCALE_LOOKBACKS:
            pr = _past_return(sym, "1h", ts, lb)
            if pr is None:
                continue
            valid += 1
            votes += 1 if pr > 0 else (-1 if pr < 0 else 0)
        gv = garch_asof(sym, ts)
        if valid == 0 or votes == 0 or gv is None:  # sin señal o sin vol → fuera del día
            continue
        out.append(
            {
                "symbol": sym,
                "direction": "BUY" if votes > 0 else "SELL",
                "confidence": round(min(abs(votes) / valid, 0.95), 4),
                "garch_vol": gv,
            }
        )
    return out


# ── Brazo A: evaluación con estado (pre-registro §3, tubería brazo A) ─────────


def run_stateful_daily(
    signals_fn, stamps: list[datetime], fee_rate: float
) -> dict:
    """Libro persistente día a día. Devuelve métricas + serie diaria + turnover."""
    equity = 1.0
    book: dict[str, float] = {}  # notional USD firmado por símbolo
    daily_rets: list[float] = []
    daily_ts: list[str] = []
    fees_paid = 0.0
    turnover_fracs: list[float] = []  # traded / equity del día (comparable en el tiempo)
    trade_days = 0

    for i in range(len(stamps) - 1):
        t0, t1 = stamps[i], stamps[i + 1]
        eq_start = equity

        # 1) decidir y operar en t0 (targets vs libro, banda 5%, fee sobre lo operado)
        qsigs = signals_fn(t0)
        positions = [
            {
                "symbol": s,
                "action": "BUY" if n > 0 else "SELL",
                "quantity": abs(n),
                "current_price": 1.0,
            }
            for s, n in book.items()
            if abs(n) > 1e-12
        ]
        legs = compute_allocations(
            qsigs, positions, budget=equity, global_mult=1.0,
            min_trade_frac=MIN_TRADE_FRAC,
        )
        traded = 0.0
        for a in legs:
            if a["action"] == "HOLD" or a["size_usd"] <= 0:
                continue
            delta = a["size_usd"] if a["action"] == "BUY" else -a["size_usd"]
            book[a["symbol"]] = book.get(a["symbol"], 0.0) + delta
            traded += a["size_usd"]
        fee = fee_rate * traded
        equity -= fee
        fees_paid += fee
        turnover_fracs.append(traded / eq_start if eq_start > 0 else 0.0)
        if traded > 0:
            trade_days += 1

        # 2) mark-to-market t0 → t1
        for sym in list(book):
            n = book[sym]
            if abs(n) < 1e-12:
                del book[sym]
                continue
            ts_list, closes = _cached_series(sym, "1h")
            p0i = bisect_right(ts_list, t0) - 1
            p1i = bisect_right(ts_list, t1) - 1
            if p0i < 0 or p1i < 0 or closes[p0i] == 0:
                continue
            r = closes[p1i] / closes[p0i] - 1.0
            equity += n * r
            book[sym] = n * (1.0 + r)

        daily_rets.append(equity / eq_start - 1.0)
        daily_ts.append(t0.isoformat())

    ann = math.sqrt(PPY_DAILY)
    eq_curve = [1.0]
    for r in daily_rets:
        eq_curve.append(eq_curve[-1] * (1 + r))
    by_year: dict[str, float] = defaultdict(lambda: 1.0)
    for ts_iso, r in zip(daily_ts, daily_rets, strict=True):
        by_year[ts_iso[:4]] *= 1 + r
    return {
        "n_days": len(daily_rets),
        "total_return": round(eq_curve[-1] - 1, 4),
        "sharpe_ann": round(sharpe_ratio(daily_rets) * ann, 4),
        "psr_zero": round(psr(daily_rets, 0.0), 4),
        "dsr_n20": round(deflated_sharpe(daily_rets, 20), 4),
        "max_dd": round(max_drawdown(eq_curve), 4),
        "ann_vol": round(_std(daily_rets) * ann, 4),
        "win_rate": round(sum(1 for r in daily_rets if r > 0) / len(daily_rets), 4),
        "avg_daily_turnover_pct_of_equity": round(
            100 * sum(turnover_fracs) / len(turnover_fracs), 2
        ),
        "ann_fee_drag_pct": round(
            100 * fee_rate * sum(turnover_fracs) / len(turnover_fracs) * PPY_DAILY, 2
        ),
        "trade_days_pct": round(100 * trade_days / len(daily_rets), 1),
        "by_year": {y: round(v - 1, 4) for y, v in sorted(by_year.items())},
    }


def main() -> None:
    import os

    os.environ.setdefault("HERMES_DUCKDB_PATH", DB)
    _load_garch()

    out: dict = {}
    solo_a = "--solo-a" in sys.argv

    # Brazo B — semanal, harness existente (idéntico a H6)
    from src.brain.backtest import run_multiscale_momentum_backtest

    for fee in FEES if not solo_a else []:
        res, rets, _eq, pts = run_multiscale_momentum_backtest(
            symbols=SYMBOLS, until=UNTIL, n_trials=1, fee_rate=fee
        )
        by_year: dict[str, float] = defaultdict(lambda: 1.0)
        for ts_iso, r in zip(pts, rets, strict=True):
            by_year[ts_iso[:4]] *= 1 + r
        out[f"B_semanal_fee{int(fee * 1e4)}bps"] = {
            "n_periods": res.n_periods,
            "total_return": res.total_return,
            "sharpe_ann": res.sharpe_ann,
            "psr_zero": res.psr_zero,
            "max_dd": res.max_drawdown,
            "win_rate": res.win_rate,
            "by_year": {y: round(v - 1, 4) for y, v in sorted(by_year.items())},
        }

    # Brazo A — diario con estado
    stamps = _iteration_stamps(SYMBOLS, "1h", "D", UNTIL)
    print(f"brazo A: {len(stamps)} stamps diarios "
          f"({stamps[0].date()} → {stamps[-1].date()})", file=sys.stderr)
    for fee in FEES:
        out[f"A_diario_fee{int(fee * 1e4)}bps"] = run_stateful_daily(
            champion_signals, stamps, fee
        )

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
