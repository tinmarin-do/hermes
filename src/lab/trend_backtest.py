"""trend_backtest — F4: TSMOM long-short canónico en el harness (trials contados).

Verificación de cierre pre-registrada (§13.1: prior bajo tras el EDA §5b — la
anatomía no muestra prima estable; se corre para cerrar la pregunta con datos).
Señal por activo: signo(retorno de lookback). Posición: vol-scaling canónico
(Moskowitz/Ooi/Pedersen), gross ≤ 1.0 (sin apalancamiento). Grilla CERRADA §13.6:
lookbacks {21, 63, 126}. Mismas 40 ventanas del window_check (seed 42); hold 28d;
costos §13.3. Vara §8.1 (aprobada por Erika ANTES de correr).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.trend_backtest"
"""

import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.h13_eval import apply_h13_bar, tsmom_window_economics, vol_scaled_signs
from src.lab.splits import partitions
from src.lab.train import load_panel
from src.lab.window_check import H, _eligible_dates, sample_windows

LOOKBACKS = (21, 63, 126)
VOL_WIN = 20
RUN_TAG = "20260713"


def prepare_panel() -> pd.DataFrame:
    """Panel diario con fwd 28d MXN, retornos de lookback y vol 20d, solo iteración."""
    panel = load_panel(H)
    g = panel.groupby("symbol", observed=True)["close"]
    for lb in LOOKBACKS:
        panel[f"ret_{lb}"] = g.pct_change(lb)
    panel["sigma20"] = g.pct_change().rolling(VOL_WIN).std().reset_index(level=0, drop=True)
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    return panel[panel["ts"].isin(iteration) & panel["fwd_ret_24h_mxn"].notna()]


def eval_lookback(
    panel: pd.DataFrame, windows: list[pd.Timestamp], lb: int
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for t0 in windows:
        day = panel[(panel["ts"] == t0) & panel["operable"]].set_index("symbol")
        signs = np.sign(day[f"ret_{lb}"])
        w = vol_scaled_signs(signs, day["sigma20"])
        r = tsmom_window_economics(day, w)
        results.append({"t0": str(t0.date()), **r})
    return results


def main() -> int:
    panel = prepare_panel()
    windows = sample_windows(_eligible_dates())
    print(f"[tsmom] {len(windows)} ventanas (idénticas a window_check, seed 42)")

    ran_at = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "generated": ran_at,
        "protocol": "§13.1/§13.6 — TSMOM canónico, vara §8.1, costos §13.3",
        "windows_t0": [str(t.date()) for t in windows],
    }
    lines = ["# F4 — TSMOM long-short (verificación de cierre)\n"]
    for lb in LOOKBACKS:
        res = eval_lookback(panel, windows, lb)
        verdict = apply_h13_bar(res)
        trial_id = f"tsmom-l{lb}-{RUN_TAG}"
        report[f"lookback_{lb}"] = {"windows": res, **verdict}
        gcs.upload_json(
            {
                "trial_id": trial_id,
                "kind": "tsmom_longshort",
                "lookback_days": lb,
                "framework": "window_check 40w seed42 · vara §8.1",
                **{k: v for k, v in verdict.items() if k != "windows"},
                "ran_at": ran_at,
            },
            f"experiments/trials/{trial_id}.json",
        )
        lines.append(
            f"## L={lb}d — {'PASA' if verdict['verdict'] else 'NO PASA'} "
            f"(W1 {verdict['w1']} · W2 {verdict['w2']} · W3 {verdict['w3']} · W4 {verdict['w4']})\n"
            f"2022+: mediana {verdict['net_median_modern']:+.2f}% · media "
            f"{verdict['net_mean_modern']:+.2f}% · por año {verdict['by_year_modern']} · "
            f"2021 {verdict['net_mean_2021']:+.2f}% · mediana-cuando-cae "
            f"{verdict['net_median_when_down']}\n"
        )
        print(
            f"[tsmom] L={lb}: 2022+ med {verdict['net_median_modern']:+.2f} media "
            f"{verdict['net_mean_modern']:+.2f} · años {verdict['by_year_modern']} · "
            f"2021 {verdict['net_mean_2021']:+.2f} · down-med {verdict['net_median_when_down']} "
            f"→ {'PASA' if verdict['verdict'] else 'NO PASA'}"
        )
    gcs.upload_json(report, "reports/h13_tsmom.json")
    gcs.upload_text("\n".join(lines), "reports/h13_tsmom.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
