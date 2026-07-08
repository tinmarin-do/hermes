"""H10.1 — Carry y flujo: funding rates + taker imbalance (pre-registro DESIGN H10 §H10.1).

4 trials: {Ridge α=1.0, LGBM chico} × {brazo A 24h diario con-estado, brazo B 7d semanal}.
Features: mom del campeón (6 en A / 4 en B) + fund_now, fund_z90, fund_d7, taker_imb,
taker_imb_z90 + dummies de símbolo. Tubería idéntica a H9 (walk-forward purgado por
stamp, scaler per-fold, dead-zone τ=0.1σ, mismos evaluadores económicos).

Varas (enmienda pre-run 3): LIVE = 4 criterios completos · SHADOW-BAR = Sharpe > vara
del brazo ∧ PSR(0) > 0.90 ∧ IC > 0 (fee 36bps). Vara campeón @36bps: A 0.9274 · B 0.9257.
"""

from __future__ import annotations

import json
import math
import os
import sys
from bisect import bisect_left, bisect_right
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/tea/hermes")
sys.path.insert(0, os.path.join(HERE, "..", "h9"))

import duckdb
import numpy as np

import pilot_h9 as PH9
from vara_h6 import SYMBOLS, UNTIL

from src.brain.backtest import _iteration_stamps

DATA_DB = os.path.join(HERE, "h10_data.duckdb")
VARA_36 = {"A": 0.9274, "B": 0.9257}
VARA_BY_YEAR_36 = {
    "A": {"2021": 3.2623, "2022": -0.4658, "2023": 0.6259, "2024": 0.3885, "2025": -0.1896},
    "B": {"2021": 2.5876, "2022": -0.4214, "2023": 1.2207, "2024": 0.1381, "2025": -0.3097},
}
ANN_FUND = 3 * 365  # funding cada 8h → anualización

_FUND: dict[str, tuple[list, list[float]]] = {}
_TAKER: dict[str, tuple[list, np.ndarray, np.ndarray]] = {}  # ts, imb_prefix, imb2_prefix


def _load_new_data() -> None:
    con = duckdb.connect(DATA_DB, read_only=True)
    try:
        for sym in SYMBOLS:
            rows = con.execute(
                "SELECT ts, rate FROM h10_funding WHERE symbol=? ORDER BY ts", [sym]
            ).fetchall()
            _FUND[sym] = ([r[0] for r in rows], [float(r[1]) for r in rows])
            rows = con.execute(
                "SELECT ts, CASE WHEN volume>0 THEN taker_buy/volume - 0.5 ELSE NULL END "
                "FROM h10_taker WHERE symbol=? ORDER BY ts", [sym]
            ).fetchall()
            ts = [r[0] for r in rows]
            imb = np.array([r[1] if r[1] is not None else 0.0 for r in rows], dtype=float)
            _TAKER[sym] = (
                ts,
                np.concatenate([[0.0], np.cumsum(imb)]),
                np.concatenate([[0.0], np.cumsum(imb * imb)]),
            )
    finally:
        con.close()


def _fund_feats(sym: str, t) -> tuple[float | None, float | None, float | None]:
    ts_list, rates = _FUND[sym]
    i = bisect_right(ts_list, t) - 1
    if i < 0:
        return None, None, None
    j7 = bisect_right(ts_list, t - timedelta(hours=168)) - 1
    j90 = bisect_left(ts_list, t - timedelta(hours=2160))
    if j7 < 0 or (i + 1 - j90) < 90:  # exige ~1 mes de historia de funding mínimo
        return None, None, None
    now = rates[i]
    win = rates[j90 : i + 1]
    mu, sd = float(np.mean(win)), float(np.std(win))
    z = (now - mu) / sd if sd > 1e-12 else None
    d7 = now - rates[j7]
    return now * ANN_FUND, z, d7 * ANN_FUND


def _taker_feats(sym: str, t) -> tuple[float | None, float | None]:
    ts_list, c1, c2 = _TAKER[sym]
    i = bisect_right(ts_list, t) - 1
    if i < 0:
        return None, None
    j24 = bisect_left(ts_list, t - timedelta(hours=24))
    j90 = bisect_left(ts_list, t - timedelta(hours=2160))
    n24, n90 = i + 1 - j24, i + 1 - j90
    if n24 < 12 or n90 < 1800:
        return None, None
    imb24 = (c1[i + 1] - c1[j24]) / n24
    mu90 = (c1[i + 1] - c1[j90]) / n90
    var90 = (c2[i + 1] - c2[j90]) / n90 - mu90 * mu90
    sd90 = math.sqrt(max(var90, 0.0))
    if sd90 <= 1e-12:
        return imb24, None
    return imb24, (imb24 - mu90) / sd90


def build_points_h101(arm: str) -> dict:
    horizon_h = 24 if arm == "A" else 168
    freq = "D" if arm == "A" else "W-MON"
    mom_lbs = PH9.MOM_LBS_A if arm == "A" else PH9.MOM_LBS_B
    stamps = _iteration_stamps(SYMBOLS, "1h", freq, UNTIL)
    dummy_syms = sorted(SYMBOLS)[1:]
    feat_names = (
        [f"mom_{lb}h" for lb in mom_lbs]
        + ["fund_now", "fund_z90", "fund_d7", "taker_imb", "taker_imb_z90"]
        + [f"dum_{s.split('/')[0]}" for s in dummy_syms]
    )
    rows, ys, ts_arr, sym_arr, gv_arr = [], [], [], [], []
    dropped = 0
    for t in stamps:
        for sym in SYMBOLS:
            moms = [PH9._mom(sym, t, lb) for lb in mom_lbs]
            _h, garch, _s = PH9._silver_asof(sym, t)
            fn, fz, fd = _fund_feats(sym, t)
            ti, tz = _taker_feats(sym, t)
            feats = moms + [fn, fz, fd, ti, tz]
            if garch is None or any(f is None for f in feats):
                dropped += 1
                continue
            p0 = PH9._close_asof(sym, t)
            p1 = PH9._close_asof(sym, t + timedelta(hours=horizon_h))
            if not p0 or not p1:
                dropped += 1
                continue
            feats = feats + [1.0 if sym == d else 0.0 for d in dummy_syms]
            ys.append((p1 / p0 - 1.0) / max(garch * math.sqrt(horizon_h), PH9.VOL_FLOOR))
            rows.append(feats)
            ts_arr.append(t)
            sym_arr.append(sym)
            gv_arr.append(garch)
    order = np.argsort(np.array(ts_arr, dtype="datetime64[s]"), kind="stable")
    print(f"brazo {arm}: {len(ys)} puntos ({dropped} descartados)", file=sys.stderr)
    return {
        "arm": arm,
        "horizon_h": horizon_h,
        "stamps": stamps,
        "feat_names": feat_names,
        "n_mom": len(mom_lbs),
        "X": np.array(rows, dtype=float)[order],
        "y": np.array(ys, dtype=float)[order],
        "ts": [ts_arr[k] for k in order],
        "sym": [sym_arr[k] for k in order],
        "gv": np.array(gv_arr, dtype=float)[order],
        "dropped": dropped,
    }


def _econ_A_n30(by_ts: dict, stamps: list, fee: float) -> dict:
    """econ brazo A con DSR a n=30 (pre-registro H10 §0)."""
    from vara_h6 import run_stateful_daily
    from src.brain.backtest import deflated_sharpe

    res = run_stateful_daily(lambda t: by_ts.get(t, []), stamps, fee, return_series=True)
    rets = res.pop("_daily_rets")
    res["dsr_n30"] = round(deflated_sharpe(rets, 30), 4)
    return res


def _econ_B_n30(by_ts: dict, fee: float) -> dict:
    """econ brazo B (semanal _evaluate) con n_trials=30."""
    from collections import defaultdict

    from src.brain.backtest import _evaluate

    iso = {t.isoformat(): v for t, v in by_ts.items()}
    try:
        res, rets, _eq, pts_ts = _evaluate(iso, "1h", 1.0, 0.10, 30, fee)
    except RuntimeError as e:
        return {"error": str(e)}
    by_year: dict[str, float] = defaultdict(lambda: 1.0)
    for ts_iso, r in zip(pts_ts, rets, strict=True):
        by_year[ts_iso[:4]] *= 1 + r
    return {
        "n_periods": res.n_periods,
        "total_return": res.total_return,
        "sharpe_ann": res.sharpe_ann,
        "psr_zero": res.psr_zero,
        "dsr_n30": res.dsr,
        "max_dd": res.max_drawdown,
        "win_rate": res.win_rate,
        "by_year": {yy: round(v - 1, 4) for yy, v in sorted(by_year.items())},
    }


def verdicts(entry: dict, arm: str) -> dict:
    ec = entry["econ_fee36bps"]
    sharpe = ec.get("sharpe_ann")
    psr0 = ec.get("psr_zero")
    ic, icp = entry["ic_spearman"], entry["ic_pvalue"]
    if sharpe is None:
        return {"live": False, "shadow_bar": False}
    vara_y = VARA_BY_YEAR_36[arm]
    ch_y = ec.get("by_year", {})
    lost_years = sum(
        1 for yy, v in vara_y.items() if yy in ch_y and ch_y[yy] < v
    )
    live = (
        ic > 0 and icp < 0.05
        and sharpe > VARA_36[arm]
        and psr0 > 0.95
        and ec.get("dsr_n30", ec.get("dsr_n20", 0)) > 0.90
        and lost_years <= 2
    )
    shadow = ic > 0 and sharpe > VARA_36[arm] and psr0 > 0.90
    return {"live": live, "shadow_bar": shadow, "años_perdidos_vs_vara": lost_years}


def main() -> None:
    os.environ.setdefault("HERMES_DUCKDB_PATH", PH9.DB)
    np.random.seed(PH9.SEED)
    PH9._load_series()
    _load_new_data()

    results: dict = {}
    for arm in ("A", "B"):
        pts = build_points_h101(arm)
        for trial, label in (("T2", "Ridge"), ("T3", "LGBM")):
            key = f"{label}_{arm}"
            print(f"== {key} ==", file=sys.stderr)
            preds = PH9.walk_forward(pts, trial)  # T2=Ridge todas, T3=LGBM todas
            ic, ic_p = PH9.spearman_ic(preds["yhat"], preds["y"])
            mask = [abs(v) >= PH9.TAU for v in preds["yhat"]]
            hits = [
                (yh > 0) == (yy > 0)
                for yh, yy, m in zip(preds["yhat"], preds["y"], mask, strict=True)
                if m and yy != 0
            ]
            entry: dict = {
                "n_oos": len(preds["y"]),
                "ic_spearman": round(ic, 4),
                "ic_pvalue": float(f"{ic_p:.3g}"),
                "r2_oos": round(preds["r2_oos"], 5),
                "hit_rate_activos": round(sum(hits) / len(hits), 4) if hits else None,
                "pct_activos": round(100 * sum(mask) / len(mask), 1) if mask else 0.0,
            }
            by_ts = PH9.signals_from_preds(preds)
            for fee in PH9.FEES:
                tag = f"econ_fee{int(fee * 1e4)}bps"
                entry[tag] = (
                    _econ_A_n30(by_ts, pts["stamps"], fee)
                    if arm == "A"
                    else _econ_B_n30(by_ts, fee)
                )
            entry["veredicto"] = verdicts(entry, arm)
            results[key] = entry
            with open(f"{HERE}/h10_1_results.json", "w") as f:
                json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
