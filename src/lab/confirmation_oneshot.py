"""ONE-SHOT del slice de confirmación — §14 (autorizado por Erika 2026-07-12).

UN solo disparo, irrepetible: el artefacto GRU congelado (sha verificado) se
evalúa UNA vez sobre el slice virgen (fechas ≥ corte de confirmación, jamás
vistas por ningún entrenamiento/validación/window_check del arco). La vara
B1/B2/B3 quedó fijada en §14 ANTES de correr; pase o falle, se documenta y el
slice queda usado para este candidato.

Corre como job:  gcloud run jobs execute hermes-lab
  --args="src.lab.confirmation_oneshot,--model-id,h12-gru-h28,--expected-sha,4a52a1d4e870"
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, run_backtest
from src.lab.dataset import extremes_label
from src.lab.splits import partitions
from src.lab.train import load_panel

MIN_OBS_SLICE = 8  # §14: el slice da ~9-10 periodos/offset — pre-registrado
BAR = {"b1_excess_mean_gt": 0.0, "b2_sin_top1_gt": 0.0, "b3_auc_gt": 0.52}


def slice_verdict(
    excess_mean: float | None, sin_top1_mean: float | None, auc: float | None
) -> dict[str, Any]:
    """Vara §14 (pura, testeable): B1∧B2∧B3. None (sin dato) = falla ese criterio."""
    b1 = excess_mean is not None and excess_mean > BAR["b1_excess_mean_gt"]
    b2 = sin_top1_mean is not None and sin_top1_mean > BAR["b2_sin_top1_gt"]
    b3 = auc is not None and auc > BAR["b3_auc_gt"]
    return {"b1_economia": b1, "b2_anti_episodio": b2, "b3_auc": b3, "pasa": b1 and b2 and b3}


def main() -> int:
    p = argparse.ArgumentParser(description="One-shot §14 del slice de confirmación")
    p.add_argument("--model-id", default="h12-gru-h28")
    p.add_argument("--expected-sha", required=True, help="sha256 (prefijo) del artefacto")
    a = p.parse_args()

    from sklearn.metrics import roc_auc_score

    from src.lab.nn_trial import NnSpec, build_sequences, predict_artifact

    art = json.loads(gcs.bucket().blob(f"models/{a.model_id}.json").download_as_text())
    if not art["sha256"].startswith(a.expected_sha):
        print(f"ABORT: sha {art['sha256'][:12]} != esperado {a.expected_sha} — artefacto cambió")
        return 1
    spec = NnSpec(**art["spec"])
    h = spec.horizon_days

    panel = extremes_label(load_panel(h), k=5)
    x_all, meta = build_sequences(panel, spec)
    _, confirmation = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(confirmation) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x_slice, meta_slice = x_all[keep], meta[keep].reset_index(drop=True)
    meta_slice["p"] = predict_artifact(art, x_slice)

    # B3 — AUC pooled sobre filas etiquetadas del slice (mismo cómputo que M4)
    labeled = meta_slice.dropna(subset=["y"])
    auc = round(float(roc_auc_score(labeled["y"], labeled["p"])), 4)

    # B1/B2 — phase check con el motor estándar (min_obs=8 pre-registrado §14)
    sig = meta_slice[meta_slice["operable"]].copy()
    dates = sorted(sig["ts"].unique())
    params = StrategyParams(
        threshold=spec.threshold, top_k=spec.top_k, horizon_days=h, min_obs=MIN_OBS_SLICE
    )
    fases: list[dict[str, Any]] = []
    for off in range(h):
        grid = pd.DatetimeIndex(dates[off::h])
        r = run_backtest(sig[sig["ts"].isin(grid)], params)
        if "error" in r:
            fases.append({"offset": off, "error": r["error"]})
            continue
        f: dict[str, Any] = {
            "offset": off,
            "excess_pct": r["excess_vs_ew_pct"],
            "net_pct": r["mean_daily_net_pct"],
            "profit_factor": r["profit_factor"],
            "periods": r["days"],
        }
        ns, bs = r.get("net_series", []), r.get("bench_series", [])
        if ns and bs:
            e = np.asarray(ns) - np.asarray(bs)
            f["exc_sin_top1_pct"] = round(float(np.delete(e, e.argmax()).mean()) * 100, 4)
        fases.append(f)

    ex = np.asarray([f["excess_pct"] for f in fases if "excess_pct" in f])
    est = [f["exc_sin_top1_pct"] for f in fases if "exc_sin_top1_pct" in f]
    pfs = [f["profit_factor"] for f in fases if f.get("profit_factor")]
    excess_mean = round(float(ex.mean()), 4) if len(ex) else None
    sin_top1 = round(float(np.mean(est)), 4) if est else None
    verdict = slice_verdict(excess_mean, sin_top1, auc)

    report: dict[str, Any] = {
        "model_id": a.model_id,
        "model_sha256": art["sha256"],
        "generated": datetime.now(UTC).isoformat(),
        "slice_from": str(pd.Timestamp(meta_slice["ts"].min()).date()),
        "slice_to": str(pd.Timestamp(meta_slice["ts"].max()).date()),
        "n_rows_scored": int(len(meta_slice)),
        "n_rows_labeled": int(len(labeled)),
        "auc_pooled": auc,
        "n_fases": int(len(ex)),
        "excess_phase_mean": excess_mean,
        "excess_min": round(float(ex.min()), 4) if len(ex) else None,
        "excess_max": round(float(ex.max()), 4) if len(ex) else None,
        "fases_positivas": int((ex > 0).sum()) if len(ex) else 0,
        "exc_sin_top1_mean": sin_top1,
        "fases_pos_sin_top1": int(sum(1 for v in est if v > 0)),
        "pf_phase_mean": round(float(np.mean(pfs)), 4) if pfs else None,
        "bar": dict(BAR),
        "verdict": verdict,
        "fases": fases,
    }
    gcs.upload_json(report, f"reports/confirmation_oneshot_{a.model_id}.json")
    print(
        f"[one-shot] {a.model_id} slice {report['slice_from']}→{report['slice_to']} · "
        f"exceso fase-media {excess_mean} ({report['fases_positivas']}/{report['n_fases']} +) · "
        f"sin-top1 {sin_top1} · AUC {auc} · PF {report['pf_phase_mean']} → "
        f"{'✅ PASA' if verdict['pasa'] else '❌ NO PASA'} "
        f"(B1={verdict['b1_economia']} B2={verdict['b2_anti_episodio']} B3={verdict['b3_auc']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
