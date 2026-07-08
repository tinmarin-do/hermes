"""H10.2 — Spreads estacionarios: reversión OU / cointegración (pre-registro DESIGN H10 §H10.2).

2 trials:
  T-neutral: long pierna barata / short pierna cara, dollar-neutral por par,
             equal-weight entre spreads activos. Fees DOBLES (2 piernas). Sim-only
             (Bitso long-only) — mide si el alpha existe.
  T-tilt:    versión long-only desplegable — tilt ±10% de la confianza del campeón
             (pierna barata ×1.10, cara ×0.90) dentro del libro brazo A con-estado.

Parámetros TODOS a priori (pre-registro): Engle-Granger rolling 90d sobre log-precios
diarios, par tradeable si p<0.05 ∧ half-life OU ∈ [2,30] días; z = resid/σ_90d;
entrada |z|>2, salida |z|<0.5 o timeout 2×half-life. Ventana 2021→2025-06-28.
Decisiones de implementación fijadas ANTES de correr (este header): hedge ratio β por
OLS del mismo rolling 90d; dollar-neutral 50/50 por par (β solo da la señal);
máx re-test EG por par: diario; fees sobre notional operado.

Varas: T-neutral compite contra CERO con costo real (PSR>0.95 ∧ DSR(n30)>0.90 ∧
Sharpe>0.5 @fees dobles) + shadow-bar NO aplica formato IC (se reporta igual).
T-tilt compite contra el campeón brazo A (Sharpe y maxDD mejores ∧ PSR>0.95 ∧
DSR>0.90) + shadow-bar (Sharpe>vara ∧ PSR>0.90).
"""

from __future__ import annotations

import json
import math
import os
import sys
from datetime import timedelta
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/tea/hermes")
sys.path.insert(0, os.path.join(HERE, "..", "h9"))

import numpy as np
from statsmodels.tsa.stattools import coint

import pilot_h9 as PH9
from vara_h6 import SYMBOLS, UNTIL, run_stateful_daily, champion_signals, _load_garch

from src.brain.backtest import (
    _iteration_stamps,
    _std,
    deflated_sharpe,
    max_drawdown,
    psr,
    sharpe_ratio,
)

WINDOW = 90  # días rolling para EG/β/σ
Z_IN, Z_OUT = 2.0, 0.5
HL_MIN, HL_MAX = 2.0, 30.0
FEES = (0.0036, 0.0010)
PPY = 365
VARA_A36 = {"sharpe": 0.9274, "max_dd": -0.6189}
OUT = HERE


def daily_log_prices(stamps) -> dict[str, np.ndarray]:
    out = {}
    for sym in SYMBOLS:
        px = [PH9._close_asof(sym, t) for t in stamps]
        out[sym] = np.array([math.log(p) if p else np.nan for p in px])
    return out


def half_life(resid: np.ndarray) -> float | None:
    dz = np.diff(resid)
    z1 = resid[:-1]
    if len(z1) < 20 or np.std(z1) < 1e-12:
        return None
    theta = -float(np.polyfit(z1, dz, 1)[0])
    if theta <= 1e-6:
        return None
    return math.log(2) / theta


def spread_signals(stamps, lp) -> dict[int, list[tuple[str, str, float]]]:
    """Por día: lista de (pierna_larga=barata, pierna_corta=cara, z). Estado abierto/cerrado."""
    pairs = list(combinations(SYMBOLS, 2))
    open_pos: dict[tuple[str, str], dict] = {}
    by_day: dict[int, list[tuple[str, str, float]]] = {}

    for i in range(WINDOW, len(stamps)):
        today: list[tuple[str, str, float]] = []
        for a, b in pairs:
            ya, yb = lp[a][i - WINDOW : i + 1], lp[b][i - WINDOW : i + 1]
            if np.isnan(ya).any() or np.isnan(yb).any():
                open_pos.pop((a, b), None)
                continue
            beta = float(np.polyfit(yb, ya, 1)[0])
            resid = ya - beta * yb
            sd = float(np.std(resid[:-1]))
            if sd < 1e-12:
                continue
            z = float((resid[-1] - np.mean(resid[:-1])) / sd)
            key = (a, b)
            pos = open_pos.get(key)
            if pos is None:
                try:
                    pval = coint(ya, yb, trend="c")[1]
                except Exception:
                    continue
                hl = half_life(resid - np.mean(resid))
                if pval < 0.05 and hl is not None and HL_MIN <= hl <= HL_MAX and abs(z) > Z_IN:
                    # z>0: a caro vs b → short a / long b; z<0: long a / short b
                    open_pos[key] = {"dir": -np.sign(z), "opened": i, "hl": hl}
                    pos = open_pos[key]
            else:
                if abs(z) < Z_OUT or (i - pos["opened"]) > 2 * pos["hl"]:
                    del open_pos[key]
                    pos = None
            if pos is not None:
                long_leg, short_leg = (b, a) if pos["dir"] < 0 else (a, b)
                today.append((long_leg, short_leg, z))
        if today:
            by_day[i] = today
    return by_day


def run_neutral(stamps, lp, by_day, fee) -> dict:
    rets_d, ts_d = [], []
    book: dict[str, float] = {}
    equity = 1.0
    for i in range(WINDOW, len(stamps) - 1):
        eq0 = equity
        legs = by_day.get(i, [])
        target: dict[str, float] = {}
        if legs:
            n = len(legs)
            per = equity / (2 * n)  # dollar-neutral: budget/2 por lado, repartido
            for lng, sht, _z in legs:
                target[lng] = target.get(lng, 0.0) + per
                target[sht] = target.get(sht, 0.0) - per
        traded = sum(abs(target.get(s, 0.0) - book.get(s, 0.0)) for s in set(target) | set(book))
        equity -= fee * traded
        book = dict(target)
        for sym in list(book):
            p0, p1 = math.exp(lp[sym][i]), math.exp(lp[sym][i + 1])
            r = p1 / p0 - 1.0
            equity += book[sym] * r
            book[sym] *= 1 + r
        rets_d.append(equity / eq0 - 1.0)
        ts_d.append(stamps[i].isoformat())
    eq_curve = [1.0]
    for r in rets_d:
        eq_curve.append(eq_curve[-1] * (1 + r))
    from collections import defaultdict

    by_year = defaultdict(lambda: 1.0)
    for t, r in zip(ts_d, rets_d, strict=True):
        by_year[t[:4]] *= 1 + r
    active_days = sum(1 for i in by_day if by_day[i])
    return {
        "n_days": len(rets_d),
        "dias_con_spreads_activos_pct": round(100 * active_days / len(rets_d), 1),
        "total_return": round(eq_curve[-1] - 1, 4),
        "sharpe_ann": round(sharpe_ratio(rets_d) * math.sqrt(PPY), 4),
        "psr_zero": round(psr(rets_d, 0.0), 4),
        "dsr_n30": round(deflated_sharpe(rets_d, 30), 4),
        "max_dd": round(max_drawdown(eq_curve), 4),
        "ann_vol": round(_std(rets_d) * math.sqrt(PPY), 4),
        "by_year": {y: round(v - 1, 4) for y, v in sorted(by_year.items())},
    }


def run_tilt(stamps, by_day, fee, idx_of) -> dict:
    def tilted(t):
        sigs = champion_signals(t)
        i = idx_of.get(t)
        if i is None:
            return sigs
        mult: dict[str, float] = {}
        for lng, sht, _z in by_day.get(i, []):
            mult[lng] = mult.get(lng, 1.0) * 1.10
            mult[sht] = mult.get(sht, 1.0) * 0.90
        for s in sigs:
            m = mult.get(s["symbol"])
            if m:
                s["confidence"] = round(min(max(s["confidence"] * m, 0.0), 0.95), 4)
        return sigs

    res = run_stateful_daily(tilted, list(stamps), fee, return_series=True)
    rets = res.pop("_daily_rets")
    res["dsr_n30"] = round(deflated_sharpe(rets, 30), 4)
    return res


def main() -> None:
    os.environ.setdefault("HERMES_DUCKDB_PATH", PH9.DB)
    PH9._load_series()
    _load_garch()
    stamps = _iteration_stamps(SYMBOLS, "1h", "D", UNTIL)
    lp = daily_log_prices(stamps)
    print("señales de spreads…", file=sys.stderr)
    by_day = spread_signals(stamps, lp)
    idx_of = {t: i for i, t in enumerate(stamps)}

    out: dict = {"n_dias_con_señal": len(by_day)}
    for fee in FEES:
        out[f"T_neutral_fee{int(fee * 1e4)}bps"] = run_neutral(stamps, lp, by_day, fee)
        out[f"T_tilt_fee{int(fee * 1e4)}bps"] = run_tilt(stamps, by_day, fee, idx_of)
        with open(f"{OUT}/h10_2_results.json", "w") as f:
            json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
