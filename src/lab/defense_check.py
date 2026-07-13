"""defense_check §15 — blindaje long-only del GRU: compuerta × vol-targeting.

La SEÑAL no se toca (receta §7.1, mismo seed): sobre las MISMAS 40 ventanas de
§13 (seed 42 — comparables 1:1 con el baseline), el GRU se re-entrena por
ventana, las predicciones se computan UNA vez y las 6 variantes de estrategia
se aplican encima. El vol-targeting importa la fórmula EXACTA del live
(`exposure_from_returns`, EWMA λ=0.94, σ_target 25%, warmup 20) alimentada con
los retornos diarios de la canasta EW operable hasta t0−1 — parámetros del
live, jamás tuneados aquí. Vara W1-W3 pre-registrada en §15 ANTES de correr.

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.defense_check"
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.brain.voltarget import exposure_from_returns
from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, _weights_for_day
from src.lab.dataset import extremes_label
from src.lab.splits import partitions
from src.lab.train import load_panel
from src.lab.window_check import COST, _eligible_dates, sample_windows, train_mask

THRESHOLDS = (0.50, 0.55, 0.60)
VOLTARGET = (False, True)
BASELINE = (0.50, False)  # ya contado (trial nn1-gru-h28); no re-registra
BAR = {"w1_excess_median_min": 1.0}
GRU_SPEC_BLOB = "experiments/specs/manual/nn1-gru-h28.json"


def variant_id(threshold: float, vt: bool) -> str:
    return f"gru-def-t{int(threshold * 100)}-{'vt' if vt else 'raw'}"


# ── funciones puras ────────────────────────────────────────────────────────────
def variant_economics(
    day: pd.DataFrame, threshold: float, m: float, top_k: int = 5, cost: float = COST
) -> dict[str, Any]:
    """Un punto económico con compuerta + exposición escalada (m ∈ [0,1]).
    El benchmark NO se escala — el blindaje se mide contra la canasta cruda."""
    w = _weights_for_day(day, StrategyParams(threshold=threshold, top_k=top_k)) * m
    invested = float(w.sum()) if len(w) else 0.0
    gross = float((w * day.loc[w.index, "fwd_ret_24h_mxn"]).sum()) if len(w) else 0.0
    net = gross - cost * invested
    bench = float(day["fwd_ret_24h_mxn"].mean()) - cost
    return {
        "net_pct": round(net * 100, 4),
        "bench_pct": round(bench * 100, 4),
        "excess_pct": round((net - bench) * 100, 4),
        "invested": round(invested, 4),
        "n_selected": int(len(w)),
    }


def aggregate_variant(windows: list[dict[str, Any]]) -> dict[str, Any]:
    net = np.asarray([w["net_pct"] for w in windows])
    ex = np.asarray([w["excess_pct"] for w in windows])
    years = pd.Series([pd.Timestamp(w["t0"]).year for w in windows])
    by_year_net = {
        int(y): round(float(net[(years == y).to_numpy()].mean()), 3) for y in sorted(years.unique())
    }
    return {
        "n_windows": len(windows),
        "net_mean": round(float(net.mean()), 3),
        "net_median": round(float(np.median(net)), 3),
        "net_worst": round(float(net.min()), 3),
        "excess_median": round(float(np.median(ex)), 3),
        "pct_excess_positive": round(float((ex > 0).mean()), 3),
        "by_year_net": by_year_net,
        "worst_year_net": round(float(min(by_year_net.values())), 3),
        "invested_mean": round(float(np.mean([w["invested"] for w in windows])), 4),
    }


def apply_bar(results: dict[str, dict[str, Any]], baseline_id: str) -> dict[str, Any]:
    """Vara §15: W1 exceso mediano ≥ +1.0 · W2 mejor neto medio · W3 mejor peor-año.
    Si nadie supera el neto medio del baseline → el blindaje no aporta."""
    base_net = results[baseline_id]["net_mean"]
    eligible = {
        k: v
        for k, v in results.items()
        if v["excess_median"] >= BAR["w1_excess_median_min"] and k != baseline_id
    }
    verdict: dict[str, Any] = {"baseline_net_mean": base_net, "eligible_w1": sorted(eligible)}
    improvers = {k: v for k, v in eligible.items() if v["net_mean"] > base_net}
    if not improvers:
        verdict |= {"winner": None, "reason": "ninguna variante W1 supera el neto del baseline"}
        return verdict
    best = max(improvers.items(), key=lambda kv: (kv[1]["net_mean"], kv[1]["worst_year_net"]))
    verdict |= {"winner": best[0], "winner_net_mean": best[1]["net_mean"]}
    return verdict


# ── corrida ────────────────────────────────────────────────────────────────────
def main() -> int:
    from src.lab.nn_trial import NnSpec, _predict, _train, build_sequences

    spec = NnSpec(**json.loads(gcs.bucket().blob(GRU_SPEC_BLOB).download_as_text()))
    panel = extremes_label(load_panel(spec.horizon_days), k=5)

    # retornos diarios de la canasta EW operable (para m_t del vol-targeting)
    op = panel[panel["operable"]].copy()
    op["ret_1d"] = op.groupby("symbol", observed=True)["close"].pct_change()
    basket = op.groupby("ts")["ret_1d"].mean().dropna().sort_index()

    x_all, meta = build_sequences(panel, spec)
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(iteration) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x_all, meta = x_all[keep], meta[keep].reset_index(drop=True)
    labeled_mask = meta["y"].notna().to_numpy()

    windows = sample_windows(_eligible_dates())
    print(f"[defense] {len(windows)} ventanas (idénticas a §13, seed 42)")

    per_variant: dict[str, list[dict[str, Any]]] = {
        variant_id(t, v): [] for t in THRESHOLDS for v in VOLTARGET
    }
    for t0 in windows:
        tr_mask = labeled_mask & train_mask(meta["ts"], t0).to_numpy()
        net = _train(x_all[tr_mask], meta.loc[tr_mask, "y"].to_numpy(), spec)
        day_mask = ((meta["ts"] == t0) & meta["operable"]).to_numpy()
        day = meta[day_mask].set_index("symbol").copy()
        day["p"] = _predict(net, x_all[day_mask])
        rets = basket[basket.index < t0].tail(400).tolist()
        m_vt = float(exposure_from_returns(rets)["m"])
        for th in THRESHOLDS:
            for vt in VOLTARGET:
                r = variant_economics(day, th, m_vt if vt else 1.0)
                per_variant[variant_id(th, vt)].append(
                    {"t0": str(t0.date()), "m": m_vt if vt else 1.0, **r}
                )
        base_exc = per_variant[variant_id(*BASELINE)][-1]["excess_pct"]
        print(f"  {t0.date()} m_vt={m_vt:.2f} · base exc {base_exc:+.2f}%")

    results = {k: aggregate_variant(v) for k, v in per_variant.items()}
    verdict = apply_bar(results, variant_id(*BASELINE))

    # registro de trials: 5 variantes NUEVAS (el baseline ya está contado)
    ran_at = datetime.now(UTC).isoformat()
    for th in THRESHOLDS:
        for vt in VOLTARGET:
            vid = variant_id(th, vt)
            if (th, vt) == BASELINE:
                continue
            gcs.upload_json(
                {
                    "trial_id": f"{vid}-20260713",
                    "kind": "strategy_variant",
                    "base_model": "nn1-gru-h28 (señal §7.1 intacta)",
                    "threshold": th,
                    "voltarget": vt,
                    "framework": "window_check §13 (mismas 40 ventanas)",
                    **results[vid],
                    "ran_at": ran_at,
                },
                f"experiments/trials/{vid}-20260713.json",
            )

    report = {
        "generated": ran_at,
        "protocol": "§15 (grilla 3x2, vara W1-W3 pre-registrada)",
        "windows_n": len(windows),
        "results": results,
        "per_window": per_variant,
        "verdict": verdict,
    }
    gcs.upload_json(report, "reports/defense_check_h12.json")
    lines = [
        "# defense_check §15 — blindaje long-only del GRU\n",
        "| variante | neto medio | neto mediano | peor ventana | peor año "
        "| exceso mediano | % exc+ | exposición |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k in sorted(results):
        r = results[k]
        lines.append(
            f"| {k} | {r['net_mean']:+.2f}% | {r['net_median']:+.2f}% | {r['net_worst']:+.2f}% "
            f"| {r['worst_year_net']:+.2f}% | {r['excess_median']:+.2f}% "
            f"| {r['pct_excess_positive']:.0%} | {r['invested_mean']:.0%} |"
        )
    lines.append(f"\nVeredicto vara §15: **{verdict.get('winner') or 'BASELINE queda'}**")
    gcs.upload_text("\n".join(lines), "reports/defense_check_h12.md")
    for k in sorted(results):
        r = results[k]
        print(
            f"[defense] {k}: neto {r['net_mean']:+.3f} · exc med {r['excess_median']:+.2f} "
            f"· peor año {r['worst_year_net']:+.2f} · exp {r['invested_mean']:.0%}"
        )
    print(f"[defense] veredicto: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
