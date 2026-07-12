"""Diagnóstico de robustez de FASE (H12 §2) — NO es un trial nuevo ni cuenta al DSR.

El backtest de un trial H>1 decide en la grilla t0+kH con UNA fase (offset 0). Este
diagnóstico re-evalúa EL MISMO modelo entrenado (mismo spec, mismo seed, mismo split
temporal) en las H fases posibles (offsets 0..H−1) y reporta la distribución del
exceso vs B&H. No se selecciona fase alguna con el resultado — es un test de
fragilidad: si el exceso solo existe en algunas fases, era suerte de calendario.
Además reporta la concentración por bloque del offset 0 (¿cuántos periodos cargan
el exceso?).

Corre como job: gcloud run jobs execute hermes-lab
  --args="src.lab.phase_check,--spec,gs://.../h12-h14.json"
Escribe reports/phase_check_<trial_id>.{json,md}.
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, run_backtest
from src.lab.dataset import extremes_label, relative_label
from src.lab.features import build_candidates, compute_matrix
from src.lab.splits import hybrid_splits, partitions
from src.lab.train import TrialSpec, _fit_predict, load_panel


def _temporal_signals(spec: TrialSpec) -> pd.DataFrame:
    """Replica el flujo de run_trial hasta las señales del holdout temporal."""
    panel = load_panel(spec.horizon_days)
    if spec.label == "rel_median":
        panel = relative_label(panel)
    elif spec.label == "extremes_k5":
        panel = extremes_label(panel, k=5)
    matrix = compute_matrix(panel, build_candidates())
    for col in ("rv_20d", "fwd_ret_24h_mxn", "operable"):
        if col not in matrix.columns:
            matrix[col] = panel[col].values
    dates = pd.DatetimeIndex(matrix["ts"].unique())
    iteration, _ = partitions(dates)
    matrix = matrix[matrix["ts"].isin(iteration)]
    matrix = matrix.dropna(subset=[*spec.features, "fwd_ret_24h_mxn"])
    labeled = matrix.dropna(subset=["y"])
    splits = hybrid_splits(iteration, seed=spec.seed, horizon_days=spec.horizon_days)
    temporal = next(s for s in splits if s.name == "temporal_holdout")
    tr = labeled[labeled["ts"].isin(temporal.train_dates)]
    va_all = matrix[matrix["ts"].isin(temporal.val_dates)]
    (p_all,) = _fit_predict(tr[spec.features], tr["y"], [va_all[spec.features]], spec)
    sig = va_all[["ts", "symbol", "rv_20d", "fwd_ret_24h_mxn", "operable"]].assign(p=p_all)
    return sig[sig["operable"]].copy()


def main(spec_uri: str) -> int:
    bucket = os.environ["HERMES_RESEARCH_BUCKET"]
    spec_dict = json.loads(
        gcs.bucket().blob(spec_uri.removeprefix(f"gs://{bucket}/")).download_as_text()
    )
    spec = TrialSpec(**spec_dict)
    h = spec.horizon_days
    sig = _temporal_signals(spec)
    dates = sorted(sig["ts"].unique())

    fases: list[dict[str, Any]] = []
    series0: list[float] = []
    for off in range(h):
        grid = pd.DatetimeIndex(dates[off::h])
        r = run_backtest(
            sig[sig["ts"].isin(grid)],
            StrategyParams(threshold=spec.threshold, top_k=spec.top_k, horizon_days=h),
        )
        if "error" in r:
            fases.append({"offset": off, "error": r["error"]})
            continue
        fases.append(
            {
                "offset": off,
                "excess_pct": r["excess_vs_ew_pct"],
                "net_pct": r["mean_daily_net_pct"],
                "bench_pct": r["benchmark_ew_daily_pct"],
                "profit_factor": r["profit_factor"],
                "total_return_pct": r["total_return_pct"],
                "periods": r["days"],
            }
        )
        ns, bs = r.get("net_series", []), r.get("bench_series", [])
        if ns and bs:
            e = np.asarray(ns) - np.asarray(bs)
            fases[-1]["exc_sin_top1_pct"] = round(float(np.delete(e, e.argmax()).mean()) * 100, 4)
        if off == 0:
            series0 = r.get("net_series", [])

    ex = np.asarray([f["excess_pct"] for f in fases if "excess_pct" in f])
    resumen = {
        "trial_id": spec.trial_id,
        "horizon_days": h,
        "generated": datetime.now(UTC).isoformat(),
        "n_fases": int(len(ex)),
        "excess_mean": round(float(ex.mean()), 4),
        "excess_min": round(float(ex.min()), 4),
        "excess_max": round(float(ex.max()), 4),
        "excess_std": round(float(ex.std(ddof=1)), 4),
        "fases_positivas": int((ex > 0).sum()),
        "fases": fases,
    }
    pfm = [f["profit_factor"] for f in fases if f.get("profit_factor")]
    est = [f["exc_sin_top1_pct"] for f in fases if "exc_sin_top1_pct" in f]
    if pfm:
        resumen["pf_phase_mean"] = round(float(np.mean(pfm)), 4)  # M2
    if est:
        resumen["exc_sin_top1_mean"] = round(float(np.mean(est)), 4)  # M3
        resumen["fases_pos_sin_top1"] = int(sum(1 for x in est if x > 0))
    if series0:
        s = np.asarray(series0)
        top = np.sort(s)[::-1]
        resumen["offset0_top1_block_pct"] = round(float(top[0]) * 100, 3)
        resumen["offset0_net_sin_top1_pct"] = round(float(np.delete(s, s.argmax()).mean()) * 100, 4)
        resumen["offset0_bloques_positivos"] = int((s > 0).sum())

    gcs.upload_json(resumen, f"reports/phase_check_{gcs.safe_name(spec.trial_id)}.json")
    lines = [
        f"# Phase check — {spec.trial_id} (H={h}d) · DIAGNÓSTICO, no cuenta como trial",
        f"\nExceso vs B&H por fase: media {resumen['excess_mean']} · rango "
        f"[{resumen['excess_min']}, {resumen['excess_max']}] · σ {resumen['excess_std']} · "
        f"positivas {resumen['fases_positivas']}/{resumen['n_fases']}\n",
        "| offset | exceso/periodo | neto | bench | PF | total% | periodos |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in fases:
        if "error" in f:
            lines.append(f"| {f['offset']} | error: {f['error']} | | | | | |")
        else:
            lines.append(
                f"| {f['offset']} | {f['excess_pct']} | {f['net_pct']} | {f['bench_pct']} "
                f"| {f['profit_factor']} | {f['total_return_pct']} | {f['periods']} |"
            )
    gcs.upload_text("\n".join(lines), f"reports/phase_check_{gcs.safe_name(spec.trial_id)}.md")
    print(
        f"[phase_check] media {resumen['excess_mean']} rango [{resumen['excess_min']}, "
        f"{resumen['excess_max']}] positivas {resumen['fases_positivas']}/{resumen['n_fases']}"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Robustez de fase H12")
    parser.add_argument("--spec", required=True)
    sys.exit(main(parser.parse_args().spec))
