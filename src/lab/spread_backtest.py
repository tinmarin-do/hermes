"""spread_backtest — F4b: spread LONG-SHORT cross-seccional del GRU (candidato principal).

La señal con mejor expediente del proyecto (ranking §7.1 de H12: 21 trials +
window_check 4/5 años + one-shot bear) cobrada por AMBOS lados: largo top-5 /
corto bottom-5 del universo operable — neutral al mercado por construcción (mata
el factor único). El bottom-5 jamás se había medido: este es el experimento.

Receta GRU INTACTA (spec congelada nn1-gru-h28), re-entrenada por ventana con
purga/embargo idéntico a window_check §13. Grilla CERRADA §13.2: pesos por pierna
∈ {ew, ivol} — 2 configs. Gross 1.0 (0.5/pierna), net 0. Costos §13.3. Vara §8.1.
Ventanas con universo < 10 se saltan y se reportan.

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.spread_backtest"
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.lab import gcs
from src.lab.dataset import extremes_label
from src.lab.h13_eval import apply_h13_bar, spread_leg_weights, spread_window_economics
from src.lab.splits import partitions
from src.lab.train import load_panel
from src.lab.window_check import GRU_SPEC_BLOB, H, _eligible_dates, sample_windows, train_mask

MODES = ("ew", "ivol")
TOP_K = 5
MIN_UNIVERSE = 2 * TOP_K
RUN_TAG = "20260713"


def main() -> int:
    from src.lab.nn_trial import NnSpec, _predict, _train, build_sequences

    spec = NnSpec(**json.loads(gcs.bucket().blob(GRU_SPEC_BLOB).download_as_text()))
    panel = extremes_label(load_panel(H), k=TOP_K)
    sig = (
        panel.groupby("symbol", observed=True)["close"]
        .pct_change()
        .rolling(20)
        .std()
        .reset_index(level=0, drop=True)
    )
    panel["sigma20"] = sig

    x_all, meta = build_sequences(panel, spec)
    # sigma20 alineada 1:1 con las secuencias (merge por símbolo+ts, sin pisar orden)
    meta = meta.merge(
        panel[["symbol", "ts", "sigma20"]], on=["symbol", "ts"], how="left", sort=False
    )
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(iteration) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x_all, meta = x_all[keep], meta[keep].reset_index(drop=True)
    labeled_mask = meta["y"].notna().to_numpy()

    windows = sample_windows(_eligible_dates())
    print(f"[spread] {len(windows)} ventanas (idénticas a window_check, seed 42)")

    per_mode: dict[str, list[dict[str, Any]]] = {m: [] for m in MODES}
    skipped: list[str] = []
    for t0 in windows:
        day_mask = ((meta["ts"] == t0) & meta["operable"]).to_numpy()
        day = meta[day_mask].set_index("symbol").copy()
        if len(day) < MIN_UNIVERSE:
            skipped.append(str(t0.date()))
            continue
        tr_mask = labeled_mask & train_mask(meta["ts"], t0).to_numpy()
        net = _train(x_all[tr_mask], meta.loc[tr_mask, "y"].to_numpy(), spec)
        day["p"] = _predict(net, x_all[day_mask])
        for m in MODES:
            w_long, w_short = spread_leg_weights(day, TOP_K, m)
            r = spread_window_economics(day, w_long, w_short)
            per_mode[m].append({"t0": str(t0.date()), **r})
        base = per_mode["ew"][-1]
        print(
            f"  {t0.date()} ew: net {base['net_pct']:+.2f}% "
            f"(L {base['long_leg_pct']:+.2f} / S {base['short_leg_pct']:+.2f}) "
            f"bench {base['bench_pct']:+.2f}%"
        )

    ran_at = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "generated": ran_at,
        "protocol": "§13.2 — spread L/S GRU congelado, vara §8.1, costos §13.3",
        "windows_skipped_lt10": skipped,
    }
    lines = ["# F4b — spread L/S cross-seccional del GRU (candidato principal)\n"]
    for m in MODES:
        res = per_mode[m]
        verdict = apply_h13_bar(res)
        long_mean = float(pd.Series([r["long_leg_pct"] for r in res]).mean())
        short_mean = float(pd.Series([r["short_leg_pct"] for r in res]).mean())
        trial_id = f"gruls-{m}-{RUN_TAG}"
        report[m] = {
            "windows": res,
            **verdict,
            "long_leg_mean_pct": round(long_mean, 3),
            "short_leg_mean_pct": round(short_mean, 3),
        }
        gcs.upload_json(
            {
                "trial_id": trial_id,
                "kind": "gru_longshort_spread",
                "leg_weighting": m,
                "base_model": "nn1-gru-h28 (receta §7.1 intacta, retrain por ventana)",
                "framework": "window_check 40w seed42 · vara §8.1",
                **{k: v for k, v in report[m].items() if k != "windows"},
                "ran_at": ran_at,
            },
            f"experiments/trials/{trial_id}.json",
        )
        lines.append(
            f"## {m} — {'PASA' if verdict['verdict'] else 'NO PASA'} "
            f"(W1 {verdict['w1']} · W2 {verdict['w2']} · W3 {verdict['w3']} · W4 {verdict['w4']})\n"
            f"2022+: mediana {verdict['net_median_modern']:+.2f}% · media "
            f"{verdict['net_mean_modern']:+.2f}% · por año {verdict['by_year_modern']} · "
            f"2021 {verdict['net_mean_2021']:+.2f}% · mediana-cuando-cae "
            f"{verdict['net_median_when_down']} · piernas L {long_mean:+.2f}/S {short_mean:+.2f}\n"
        )
        print(
            f"[spread] {m}: 2022+ med {verdict['net_median_modern']:+.2f} media "
            f"{verdict['net_mean_modern']:+.2f} · años {verdict['by_year_modern']} · "
            f"2021 {verdict['net_mean_2021']:+.2f} · down-med {verdict['net_median_when_down']} "
            f"· piernas L{long_mean:+.2f}/S{short_mean:+.2f} "
            f"→ {'PASA' if verdict['verdict'] else 'NO PASA'}"
        )
    gcs.upload_json(report, "reports/h13_spread.json")
    gcs.upload_text("\n".join(lines), "reports/h13_spread.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
