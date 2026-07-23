"""spread_oneshot — F6: one-shot SECUNDARIO del spread L/S en el slice (§9.1).

Modo DEPLOYMENT: la spec congelada `h13-gruls-ivol` (sha verificado) apunta al
artefacto GRU congelado de H12 (sha verificado) que puntúa el slice UNA vez —
CERO re-entrenos. 28 fases escalonadas (offsets 0..27, hold 28d), economía L/S
con costos §13.3 pagados completos en cada rebalanceo (conservador).

Vara S1/S2 pre-registrada en §9.1 ANTES de correr. DOBLE CAVEAT permanente: el
slice ya fue consumido por esta familia (H12 §14) y el operador conoce su
contenido → gane o pierda, esto es evidencia DÉBIL del expediente; el juez
primario es el shadow forward (§9.1b).

Corre como job:  gcloud run jobs execute hermes-lab
  --args="src.lab.spread_oneshot,--expected-sha,0dac692a"
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.dataset import extremes_label
from src.lab.h13_eval import spread_leg_weights, spread_window_economics
from src.lab.splits import partitions
from src.lab.train import load_panel

SPEC_BLOB = "models/h13-gruls-ivol.json"
MIN_UNIVERSE = 10
BAR = {"s1_phase_mean_gt": 0.0, "s2_pct_phases_pos_min": 0.55}


def slice_verdict(phase_mean: float | None, pct_pos: float | None) -> dict[str, Any]:
    """Vara §9.1 (pura, testeable). None = falla ese criterio."""
    s1 = phase_mean is not None and phase_mean > BAR["s1_phase_mean_gt"]
    s2 = pct_pos is not None and pct_pos >= BAR["s2_pct_phases_pos_min"]
    return {"s1_economia": s1, "s2_consistencia": s2, "pasa": s1 and s2}


def main() -> int:
    p = argparse.ArgumentParser(description="One-shot secundario §9.1 del spread L/S")
    p.add_argument("--expected-sha", required=True, help="sha256 (prefijo) de la spec")
    a = p.parse_args()

    from src.lab.nn_trial import NnSpec, build_sequences, predict_artifact

    spec = json.loads(gcs.bucket().blob(SPEC_BLOB).download_as_text())
    if not spec["sha256"].startswith(a.expected_sha):
        print(f"ABORT: spec sha {spec['sha256'][:12]} != esperado {a.expected_sha}")
        return 1
    art = json.loads(gcs.bucket().blob(spec["model_ref"]).download_as_text())
    if art["sha256"] != spec["model_sha256"]:
        print("ABORT: el artefacto del modelo no coincide con el sha congelado en la spec")
        return 1

    nn_spec = NnSpec(**art["spec"])
    h = int(spec["cadence_days"])
    panel = extremes_label(load_panel(h), k=int(spec["top_k"]))
    sig = (
        panel.groupby("symbol", observed=True)["close"]
        .pct_change()
        .rolling(int(spec["sigma_window_days"]))
        .std()
        .reset_index(level=0, drop=True)
    )
    panel["sigma20"] = sig

    x_all, meta = build_sequences(panel, nn_spec)
    meta = meta.merge(
        panel[["symbol", "ts", "sigma20"]], on=["symbol", "ts"], how="left", sort=False
    )
    _, confirmation = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(confirmation) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x_slice, meta_slice = x_all[keep], meta[keep].reset_index(drop=True)
    meta_slice["p"] = predict_artifact(art, x_slice)
    op = meta_slice[meta_slice["operable"]]
    dates = sorted(op["ts"].unique())

    fases: list[dict[str, Any]] = []
    for off in range(h):
        nets: list[float] = []
        longs: list[float] = []
        shorts: list[float] = []
        for t0 in dates[off::h]:
            day = op[op["ts"] == t0].set_index("symbol")
            if len(day) < MIN_UNIVERSE or day["sigma20"].isna().all():
                continue
            w_long, w_short = spread_leg_weights(
                day, int(spec["top_k"]), str(spec["leg_weighting"])
            )
            r = spread_window_economics(day, w_long, w_short)
            nets.append(r["net_pct"])
            longs.append(r["long_leg_pct"])
            shorts.append(r["short_leg_pct"])
        if nets:
            fases.append(
                {
                    "offset": off,
                    "periods": len(nets),
                    "net_mean_pct": round(float(np.mean(nets)), 4),
                    "long_mean_pct": round(float(np.mean(longs)), 4),
                    "short_mean_pct": round(float(np.mean(shorts)), 4),
                }
            )

    means = np.asarray([f["net_mean_pct"] for f in fases])
    phase_mean = round(float(means.mean()), 4) if len(means) else None
    pct_pos = round(float((means > 0).mean()), 4) if len(means) else None
    verdict = slice_verdict(phase_mean, pct_pos)

    report: dict[str, Any] = {
        "spec_id": spec["spec_id"],
        "spec_sha256": spec["sha256"],
        "model_sha256": art["sha256"],
        "generated": datetime.now(UTC).isoformat(),
        "mode": "deployment (cero re-entrenos)",
        "slice_from": str(pd.Timestamp(op["ts"].min()).date()),
        "slice_to": str(pd.Timestamp(op["ts"].max()).date()),
        "n_fases": int(len(fases)),
        "phase_mean_net_pct": phase_mean,
        "pct_phases_positive": pct_pos,
        "phase_min": round(float(means.min()), 4) if len(means) else None,
        "phase_max": round(float(means.max()), 4) if len(means) else None,
        "long_mean_pct": round(float(np.mean([f["long_mean_pct"] for f in fases])), 4)
        if fases
        else None,
        "short_mean_pct": round(float(np.mean([f["short_mean_pct"] for f in fases])), 4)
        if fases
        else None,
        "bar": dict(BAR),
        "verdict": verdict,
        "doble_caveat": "slice consumido por la familia GRU (H12 §14) + operador conoce "
        "el contenido — evidencia DÉBIL; juez primario = shadow forward §9.1b",
        "fases": fases,
    }
    gcs.upload_json(report, "reports/spread_oneshot_h13.json")
    print(
        f"[spread-oneshot] {spec['spec_id']} slice {report['slice_from']}→{report['slice_to']} · "
        f"fase-media {phase_mean} ({pct_pos:.0%} fases +) · piernas L {report['long_mean_pct']} / "
        f"S {report['short_mean_pct']} → "
        f"{'✅ S1/S2 PASA' if verdict['pasa'] else '❌ NO PASA'} "
        f"(evidencia secundaria, doble caveat)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
