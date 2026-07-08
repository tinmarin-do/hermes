"""H9 — Piloto del challenger de regresión (pre-registro docs/DESIGN_regression_challenger.md).

6 trials pre-registrados: {T1 Ridge solo-mom, T2 Ridge completo, T3 LGBM chico} × {brazo A
24h diario con-estado, brazo B 7d semanal}. Matriz de features construida UNA vez por brazo
y compartida por los 3 modelos. Walk-forward: fit pooled POR STAMP con train = puntos
anteriores que respetan purga 500h + embargo = horizonte del brazo. Normalización
per-fold (solo Ridge; LGBM invariante). Seed 42. $0: sin LLM/GCP/red.
Ventana 2021-01-01 → 2025-06-28 (holdout intocado).
"""

from __future__ import annotations

import json
import math
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import timedelta

sys.path.insert(0, "/home/tea/hermes")
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))

import duckdb
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from vara_h6 import DB, SYMBOLS, UNTIL, run_stateful_daily  # evaluador con-estado compartido

from src.brain.backtest import _evaluate, _iteration_stamps

SEED = 42
PURGE_H = 500  # ventana GARCH (la rolling más larga) — pre-registro §3
TAU = 0.10  # dead-zone en unidades de σ — pre-registro §3
CONF_CAP = 0.95
MIN_TRAIN = 100
FEES = (0.0036, 0.0010)
VOL_FLOOR = 1e-4

MOM_LBS_A = (24, 72, 168, 336, 720, 2160)  # brazo A: + escalas cortas (enmienda 2)
MOM_LBS_B = (168, 336, 720, 2160)  # brazo B: las 4 del campeón
REGIME_FEATS = ("hurst", "garch_vol", "spread", "vol_z")

OUT = __import__("os").path.dirname(__import__("os").path.abspath(__file__))


# ── carga única de series por símbolo ────────────────────────────────────────

_SERIES: dict[str, dict] = {}


def _load_series() -> None:
    con = duckdb.connect(DB, read_only=True)
    try:
        for sym in SYMBOLS:
            rows = con.execute(
                "SELECT ts, close, volume FROM bronze_ohlcv "
                "WHERE symbol=? AND timeframe='1h' ORDER BY ts",
                [sym],
            ).fetchall()
            ts = [r[0] for r in rows]
            close = np.array([r[1] for r in rows], dtype=float)
            vol = np.array([r[2] for r in rows], dtype=float)
            srows = con.execute(
                "SELECT ts, hurst, garch_vol, spread FROM silver_features "
                "WHERE symbol=? AND timeframe='1h' ORDER BY ts",
                [sym],
            ).fetchall()
            _SERIES[sym] = {
                "ts": ts,
                "close": close,
                "vol_cum": np.concatenate([[0.0], np.cumsum(vol)]),
                "vol2_cum": np.concatenate([[0.0], np.cumsum(vol * vol)]),
                "s_ts": [r[0] for r in srows],
                "hurst": [r[1] for r in srows],
                "garch": [r[2] for r in srows],
                "spread": [r[3] for r in srows],
            }
    finally:
        con.close()


def _asof_idx(ts_list, t) -> int:
    return bisect_right(ts_list, t) - 1


def _close_asof(sym: str, t) -> float | None:
    s = _SERIES[sym]
    i = _asof_idx(s["ts"], t)
    return float(s["close"][i]) if i >= 0 else None


def _silver_asof(sym: str, t) -> tuple[float | None, float | None, float | None]:
    s = _SERIES[sym]
    i = _asof_idx(s["s_ts"], t)
    if i < 0:
        return None, None, None
    h, g, sp = s["hurst"][i], s["garch"][i], s["spread"][i]
    return (
        float(h) if h is not None else None,
        float(g) if g is not None else None,
        float(sp) if sp is not None else None,
    )


def _vol_z(sym: str, t) -> float | None:
    """(μ_vol_7d − μ_vol_90d) / σ_vol_90d sobre volumen horario — pre-registro §4."""
    s = _SERIES[sym]
    i = _asof_idx(s["ts"], t)  # inclusive
    if i < 0:
        return None
    j7 = bisect_left(s["ts"], t - timedelta(hours=168))
    j90 = bisect_left(s["ts"], t - timedelta(hours=2160))
    n7, n90 = i + 1 - j7, i + 1 - j90
    if n7 < 24 or n90 < 1800:  # exige historia casi completa de 90d
        return None
    c, c2 = s["vol_cum"], s["vol2_cum"]
    mu7 = (c[i + 1] - c[j7]) / n7
    mu90 = (c[i + 1] - c[j90]) / n90
    var90 = (c2[i + 1] - c2[j90]) / n90 - mu90 * mu90
    sd90 = math.sqrt(max(var90, 0.0))
    if sd90 <= 1e-12:
        return None
    return (mu7 - mu90) / sd90


def _mom(sym: str, t, lb_h: int) -> float | None:
    now = _close_asof(sym, t)
    then = _close_asof(sym, t - timedelta(hours=lb_h))
    return now / then - 1.0 if (now and then) else None


# ── matriz de puntos por brazo (features + target), construida UNA vez ────────


def build_points(arm: str) -> dict:
    """arm 'A' (diario, 24h) | 'B' (semanal, 7d). Devuelve arrays alineados."""
    horizon_h = 24 if arm == "A" else 168
    freq = "D" if arm == "A" else "W-MON"
    mom_lbs = MOM_LBS_A if arm == "A" else MOM_LBS_B
    stamps = _iteration_stamps(SYMBOLS, "1h", freq, UNTIL)

    # Dummies de símbolo (pre-registro §5: "pooled cross-symbol CON dummy de símbolo";
    # conformidad tras hallazgo 0 de la auditoría 2026-07-07 — la 1ª corrida los omitió).
    # drop-first: 5 columnas para 6 símbolos; el intercepto absorbe al primero.
    dummy_syms = sorted(SYMBOLS)[1:]
    feat_names = (
        [f"mom_{lb}h" for lb in mom_lbs]
        + list(REGIME_FEATS)
        + [f"dum_{s.split('/')[0]}" for s in dummy_syms]
    )
    rows, ys, ts_arr, sym_arr, gv_arr = [], [], [], [], []
    for t in stamps:
        for sym in SYMBOLS:
            moms = [_mom(sym, t, lb) for lb in mom_lbs]
            hurst, garch, spread = _silver_asof(sym, t)
            vz = _vol_z(sym, t)
            feats = moms + [hurst, garch, spread, vz]
            if any(f is None for f in feats):
                continue
            feats = feats + [1.0 if sym == d else 0.0 for d in dummy_syms]
            p0 = _close_asof(sym, t)
            p1 = _close_asof(sym, t + timedelta(hours=horizon_h))
            if not p0 or not p1:
                continue
            fwd = p1 / p0 - 1.0
            y = fwd / max(garch * math.sqrt(horizon_h), VOL_FLOOR)
            rows.append(feats)
            ys.append(y)
            ts_arr.append(t)
            sym_arr.append(sym)
            gv_arr.append(garch)
    order = np.argsort(np.array(ts_arr, dtype="datetime64[s]"), kind="stable")
    X = np.array(rows, dtype=float)[order]
    return {
        "arm": arm,
        "horizon_h": horizon_h,
        "stamps": stamps,
        "feat_names": feat_names,
        "n_mom": len(mom_lbs),
        "X": X,
        "y": np.array(ys, dtype=float)[order],
        "ts": [ts_arr[k] for k in order],
        "sym": [sym_arr[k] for k in order],
        "gv": np.array(gv_arr, dtype=float)[order],
    }


# ── walk-forward pooled por stamp ─────────────────────────────────────────────


def make_model(trial: str):
    if trial in ("T1", "T2"):
        return Ridge(alpha=1.0)
    import lightgbm as lgb

    return lgb.LGBMRegressor(
        max_depth=3, n_estimators=300, learning_rate=0.05, min_child_samples=100,
        subsample=0.8, colsample_bytree=0.8, random_state=SEED, verbose=-1,
        n_jobs=4,  # amable con la compu de Erika; no cambia el resultado, solo la velocidad
    )


def walk_forward(pts: dict, trial: str) -> dict:
    """Predicciones OOS por stamp. T1 usa solo mom; T2/T3 todas. Scaler per-fold (Ridge).

    Los dummies de símbolo (últimas 5 columnas) van en TODOS los trials: son la
    infraestructura del pooling (§5), no una feature de la escalera.
    """
    n_feat = pts["X"].shape[1]
    dummy_cols = list(range(n_feat - 5, n_feat))
    cols = (
        list(range(pts["n_mom"])) + dummy_cols if trial == "T1" else list(range(n_feat))
    )
    X, y, ts = pts["X"][:, cols], pts["y"], pts["ts"]
    ts_np = np.array(ts, dtype="datetime64[s]")
    gap = np.timedelta64(PURGE_H + pts["horizon_h"], "h")

    preds: dict = {"ts": [], "sym": [], "yhat": [], "y": [], "gv": []}
    baseline_sse = pred_sse = 0.0
    stamp_groups: dict = defaultdict(list)
    for i, t in enumerate(ts):
        stamp_groups[t].append(i)

    uniq_stamps = sorted(stamp_groups)
    for k, t in enumerate(uniq_stamps):
        cutoff = np.datetime64(t, "s") - gap
        n_train = int(np.searchsorted(ts_np, cutoff, side="right"))
        if n_train < MIN_TRAIN:
            continue
        Xtr, ytr = X[:n_train], y[:n_train]
        idx_test = stamp_groups[t]
        Xte = X[idx_test]
        if trial in ("T1", "T2"):
            sc = StandardScaler().fit(Xtr)
            model = make_model(trial).fit(sc.transform(Xtr), ytr)
            yhat = model.predict(sc.transform(Xte))
        else:
            model = make_model(trial).fit(Xtr, ytr)
            yhat = model.predict(Xte)
        mu_tr = float(ytr.mean())
        for j, i in enumerate(idx_test):
            preds["ts"].append(t)
            preds["sym"].append(pts["sym"][i])
            preds["yhat"].append(float(yhat[j]))
            preds["y"].append(float(y[i]))
            preds["gv"].append(float(pts["gv"][i]))
            baseline_sse += (y[i] - mu_tr) ** 2
            pred_sse += (y[i] - yhat[j]) ** 2
        if k % 200 == 0:
            print(f"  {trial}/{pts['arm']}: stamp {k}/{len(uniq_stamps)}", file=sys.stderr)

    preds["r2_oos"] = 1.0 - pred_sse / baseline_sse if baseline_sse > 0 else 0.0
    return preds


# ── métricas predictivas + económicas ────────────────────────────────────────


def spearman_ic(yhat: list[float], y: list[float]) -> tuple[float, float]:
    try:
        from scipy.stats import spearmanr

        rho, p = spearmanr(yhat, y)
        return float(rho), float(p)
    except ImportError:  # aproximación normal si no hay scipy
        n = len(y)
        rk = lambda v: np.argsort(np.argsort(v))
        rho = float(np.corrcoef(rk(np.array(yhat)), rk(np.array(y)))[0, 1])
        z = rho * math.sqrt(max(n - 3, 1))
        p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
        return rho, p


def signals_from_preds(preds: dict) -> dict:
    """ts → [qsig] con dead-zone τ y conf=min(|ŷ|,0.95) — pre-registro §3."""
    by_ts: dict = defaultdict(list)
    for t, sym, yhat, gv in zip(preds["ts"], preds["sym"], preds["yhat"], preds["gv"], strict=True):
        if abs(yhat) < TAU:
            continue
        by_ts[t].append(
            {
                "symbol": sym,
                "direction": "BUY" if yhat > 0 else "SELL",
                "confidence": round(min(abs(yhat), CONF_CAP), 4),
                "garch_vol": gv,
                "_ts": t,
            }
        )
    return by_ts


def econ_arm_B(by_ts: dict, fee: float) -> dict:
    iso = {t.isoformat(): v for t, v in by_ts.items()}
    try:
        res, rets, _eq, pts = _evaluate(iso, "1h", 1.0, 0.10, 20, fee)
    except RuntimeError as e:  # demasiado pocos períodos activos
        return {"error": str(e)}
    by_year: dict[str, float] = defaultdict(lambda: 1.0)
    for ts_iso, r in zip(pts, rets, strict=True):
        by_year[ts_iso[:4]] *= 1 + r
    return {
        "n_periods": res.n_periods,
        "total_return": res.total_return,
        "sharpe_ann": res.sharpe_ann,
        "psr_zero": res.psr_zero,
        "dsr_n20": res.dsr,
        "max_dd": res.max_drawdown,
        "win_rate": res.win_rate,
        "by_year": {yy: round(v - 1, 4) for yy, v in sorted(by_year.items())},
    }


def econ_arm_A(by_ts: dict, stamps: list, fee: float) -> dict:
    return run_stateful_daily(lambda t: by_ts.get(t, []), stamps, fee)


def main() -> None:
    import os

    os.environ.setdefault("HERMES_DUCKDB_PATH", DB)
    np.random.seed(SEED)
    _load_series()

    results: dict = {}
    for arm in ("A", "B"):
        print(f"== construyendo matriz brazo {arm} ==", file=sys.stderr)
        pts = build_points(arm)
        print(f"   {len(pts['y'])} puntos, {pts['X'].shape[1]} features", file=sys.stderr)
        for trial in ("T1", "T2", "T3"):
            key = f"{trial}_{arm}"
            print(f"== {key} ==", file=sys.stderr)
            preds = walk_forward(pts, trial)
            ic, ic_p = spearman_ic(preds["yhat"], preds["y"])
            mask = [abs(v) >= TAU for v in preds["yhat"]]
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
            by_ts = signals_from_preds(preds)
            for fee in FEES:
                tag = f"econ_fee{int(fee * 1e4)}bps"
                entry[tag] = (
                    econ_arm_A(by_ts, pts["stamps"], fee)
                    if arm == "A"
                    else econ_arm_B(by_ts, fee)
                )
            results[key] = entry
            with open(f"{OUT}/pilot_results.json", "w") as f:
                json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
