"""window_check §13 — economía en ventanas aleatorias multi-año (idea Erika 2026-07-12).

Los block draws miden AUC/acc entre regímenes; este diagnóstico hace lo mismo con
el DINERO: W=40 ventanas de 28d no solapadas sorteadas sobre toda la iteración,
re-entrenando el candidato por ventana con purga/embargo de 28d a ambos lados
(≈ CPCV). Una ventana = UN punto económico coherente (decisión en t0, hold 28d,
costo de entrada completo en estrategia Y benchmark).

Reglas §13 (pre-registradas ANTES de correr — la vara no se ablanda):
- MISMAS ventanas para ambos candidatos (elegibilidad = intersección).
- Vara: mediana>0 · ≥55% ventanas positivas · ningún año con media < −1.0%.
- Es DIAGNÓSTICO simétrico sobre candidatos ya contados — n_trials no cambia.
- Caveat: el re-entreno ve futuro relativo a su ventana → robustez de señal,
  no deployabilidad (el shadow sigue siendo el juez de deploy).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.window_check"
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.backtest_daily import FEE_RATE, SLIPPAGE, StrategyParams, _weights_for_day
from src.lab.dataset import extremes_label
from src.lab.features import build_candidates, compute_matrix
from src.lab.splits import partitions
from src.lab.train import TrialSpec, load_panel

H = 28
W_TARGET = 40
SEED = 42
PURGE = H  # labels que solapan la ventana quedan fuera del train
EMBARGO = H
COST = FEE_RATE + SLIPPAGE
BAR = {"median_gt": 0.0, "pct_positive_min": 0.55, "year_mean_min": -1.0}
GRU_SPEC_BLOB = "experiments/specs/manual/nn1-gru-h28.json"
CHAMPION_SPEC_BLOB = "experiments/specs/manual/h12-h28.json"


# ── funciones puras ────────────────────────────────────────────────────────────
def sample_windows(
    eligible: pd.DatetimeIndex, h: int = H, target: int = W_TARGET, seed: int = SEED
) -> list[pd.Timestamp]:
    """t0 no solapados (|Δ| ≥ h días), sorteo determinista sobre fechas elegibles."""
    pool = pd.DatetimeIndex(eligible).sort_values()
    order = np.random.default_rng(seed).permutation(len(pool))
    chosen: list[pd.Timestamp] = []
    for i in order:
        t0 = pool[i]
        if all(abs((t0 - c).days) >= h for c in chosen):
            chosen.append(t0)
            if len(chosen) >= target:
                break
    return sorted(chosen)


def train_mask(ts: pd.Series, t0: pd.Timestamp, purge: int = PURGE, embargo: int = EMBARGO) -> Any:
    """Train = fechas fuera de [t0−purga, t0+H+embargo] (ningún label toca la ventana)."""
    lo = t0 - pd.Timedelta(days=purge)
    hi = t0 + pd.Timedelta(days=H + embargo)
    return ~((ts >= lo) & (ts <= hi))


def window_economics(
    day: pd.DataFrame, threshold: float, top_k: int, cost: float = COST
) -> dict[str, Any]:
    """Un punto económico: decisión en t0 con p, hold 28d, entrada completa pagada
    por AMBOS lados (estrategia y benchmark EW) — comparable y conservador."""
    w = _weights_for_day(day, StrategyParams(threshold=threshold, top_k=top_k))
    gross = float((w * day.loc[w.index, "fwd_ret_24h_mxn"]).sum()) if len(w) else 0.0
    net = gross - cost * float(w.sum()) if len(w) else 0.0
    bench = float(day["fwd_ret_24h_mxn"].mean()) - cost
    return {
        "net_pct": round(net * 100, 4),
        "bench_pct": round(bench * 100, 4),
        "excess_pct": round((net - bench) * 100, 4),
        "n_selected": int(len(w)),
        "n_universe": int(len(day)),
    }


def aggregate(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distribución del exceso + desglose anual + veredicto contra la vara §13."""
    ex = np.asarray([w["excess_pct"] for w in windows])
    years = pd.Series([pd.Timestamp(w["t0"]).year for w in windows])
    by_year = {
        int(y): round(float(ex[(years == y).to_numpy()].mean()), 3) for y in sorted(years.unique())
    }
    out: dict[str, Any] = {
        "n_windows": len(windows),
        "excess_median": round(float(np.median(ex)), 3),
        "excess_mean": round(float(ex.mean()), 3),
        "pct_positive": round(float((ex > 0).mean()), 3),
        "excess_min": round(float(ex.min()), 3),
        "excess_max": round(float(ex.max()), 3),
        "by_year": by_year,
        "bar": dict(BAR),
    }
    out["pass_median"] = out["excess_median"] > BAR["median_gt"]
    out["pass_pct_positive"] = out["pct_positive"] >= BAR["pct_positive_min"]
    out["pass_years"] = all(v >= BAR["year_mean_min"] for v in by_year.values())
    out["verdict"] = bool(out["pass_median"] and out["pass_pct_positive"] and out["pass_years"])
    return out


# ── candidatos ─────────────────────────────────────────────────────────────────
def _champion_eval(windows: list[pd.Timestamp]) -> list[dict[str, Any]]:
    spec = TrialSpec(**json.loads(gcs.bucket().blob(CHAMPION_SPEC_BLOB).download_as_text()))
    panel = extremes_label(load_panel(H), k=5)
    matrix = compute_matrix(panel, build_candidates())
    matrix["operable"] = panel["operable"].values
    iteration, _ = partitions(pd.DatetimeIndex(matrix["ts"].unique()))
    matrix = matrix[matrix["ts"].isin(iteration)].dropna(subset=[*spec.features, "fwd_ret_24h_mxn"])
    labeled = matrix.dropna(subset=["y"])

    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    results = []
    for t0 in windows:
        tr = labeled[train_mask(labeled["ts"], t0)]
        scaler = StandardScaler().fit(tr[spec.features])
        clf = LogisticRegression(
            max_iter=1000,
            C=float(spec.params.get("C", 1.0)),
            class_weight=spec.params.get("class_weight"),
            random_state=spec.seed,
        ).fit(scaler.transform(tr[spec.features]), tr["y"])
        day = matrix[(matrix["ts"] == t0) & matrix["operable"]].set_index("symbol")
        p = clf.predict_proba(scaler.transform(day[spec.features]))[:, 1]
        r = window_economics(day.assign(p=p), spec.threshold, spec.top_k)
        results.append({"t0": str(t0.date()), **r})
        print(f"  [champion] {t0.date()} exceso {r['excess_pct']:+.2f}% (k={r['n_selected']})")
    return results


def _gru_eval(windows: list[pd.Timestamp]) -> list[dict[str, Any]]:
    from src.lab.nn_trial import NnSpec, _predict, _train, build_sequences

    spec = NnSpec(**json.loads(gcs.bucket().blob(GRU_SPEC_BLOB).download_as_text()))
    panel = extremes_label(load_panel(H), k=5)
    x_all, meta = build_sequences(panel, spec)
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(iteration) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x_all, meta = x_all[keep], meta[keep].reset_index(drop=True)
    labeled_mask = meta["y"].notna().to_numpy()

    results = []
    for t0 in windows:
        tr_mask = labeled_mask & train_mask(meta["ts"], t0).to_numpy()
        net = _train(x_all[tr_mask], meta.loc[tr_mask, "y"].to_numpy(), spec)
        day_mask = ((meta["ts"] == t0) & meta["operable"]).to_numpy()
        day = meta[day_mask].set_index("symbol").copy()
        day["p"] = _predict(net, x_all[day_mask])
        r = window_economics(day, spec.threshold, spec.top_k)
        results.append({"t0": str(t0.date()), **r})
        print(f"  [gru] {t0.date()} exceso {r['excess_pct']:+.2f}% (k={r['n_selected']})")
    return results


def _eligible_dates() -> pd.DatetimeIndex:
    """Fechas de iteración donde AMBOS candidatos tienen universo operable ≥ 6:
    ret_63d válido (campeón) y secuencia 84d válida (GRU, la más estricta)."""
    panel = load_panel(H)
    g = panel.groupby("symbol", observed=True)["close"]
    panel["ret_63d"] = g.pct_change(63)
    # proxy de secuencia GRU válida: 84+20 días de historia del símbolo
    panel["hist_days"] = panel.groupby("symbol", observed=True).cumcount()
    ok = panel[
        panel["operable"]
        & panel["ret_63d"].notna()
        & panel["fwd_ret_24h_mxn"].notna()
        & (panel["hist_days"] >= 84 + 20)
    ]
    counts = ok.groupby("ts")["symbol"].nunique()
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    dates = pd.DatetimeIndex(counts[counts >= 6].index)
    return dates[dates.isin(iteration)]


def main() -> int:
    windows = sample_windows(_eligible_dates())
    print(f"[window_check] {len(windows)} ventanas ({windows[0].date()} → {windows[-1].date()})")
    report: dict[str, Any] = {
        "generated": datetime.now(UTC).isoformat(),
        "protocol": {"W": W_TARGET, "h": H, "seed": SEED, "purge": PURGE, "embargo": EMBARGO},
        "windows_t0": [str(t.date()) for t in windows],
    }
    lines = ["# window_check §13 — economía en ventanas aleatorias multi-año\n"]
    for name, fn in (("champion_ext5_h28", _champion_eval), ("gru_h28", _gru_eval)):
        res = fn(windows)
        agg = aggregate(res)
        report[name] = {"windows": res, **agg}
        lines += [
            f"## {name}: mediana {agg['excess_median']:+.2f}% · media {agg['excess_mean']:+.2f}% "
            f"· positivas {agg['pct_positive']:.0%} · rango [{agg['excess_min']}, "
            f"{agg['excess_max']}] · **{'PASA' if agg['verdict'] else 'NO PASA'} la vara §13**",
            f"por año: {agg['by_year']}\n",
        ]
        print(
            f"[window_check] {name}: mediana {agg['excess_median']:+.3f} · "
            f"positivas {agg['pct_positive']:.0%} · años {agg['by_year']} · "
            f"veredicto {'PASA' if agg['verdict'] else 'NO PASA'}"
        )
    gcs.upload_json(report, "reports/window_check_h12.json")
    gcs.upload_text("\n".join(lines), "reports/window_check_h12.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
