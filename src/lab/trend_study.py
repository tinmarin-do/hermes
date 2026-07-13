"""trend_study — estructura de tendencia por horizonte y régimen (H13 §5b, EDA).

Prerequisito descriptivo del TSMOM (F4): mide si el SIGNO del retorno pasado de H
días dice algo del retorno de los H siguientes — con ventanas NO solapadas (paso H)
para no inflar la estadística por autocorrelación mecánica.

Métricas por horizonte H, pooled y por año y por tercil de vol:
- persistencia de signo: P(sign(fwd_H) == sign(past_H))
- prima de tendencia cruda: E[fwd_H | past_H>0] − E[fwd_H | past_H<0]
  (SIN costos ni posiciones — descriptivo, NO cuenta al DSR; la economía con
  costos es F4 y ahí sí se cuentan trials).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.trend_study"
"""

import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs

HORIZONS = (1, 2, 3, 5, 10, 21, 42, 63, 126)
VOL_WINDOW = 20


def _sign_stats(past: pd.Series, fwd: pd.Series) -> dict[str, Any]:
    ok = past.notna() & fwd.notna() & (past != 0)
    if int(ok.sum()) < 30:
        return {"n": int(ok.sum())}
    p, f = past[ok], fwd[ok]
    up = p > 0
    out: dict[str, Any] = {
        "n": int(ok.sum()),
        "persistence": round(float((np.sign(p) == np.sign(f)).mean()), 4),
    }
    # la prima exige ambos lados poblados (una serie puro-drift no tiene lado down)
    if int(up.sum()) >= 5 and int((~up).sum()) >= 5:
        out["fwd_up_mean_pct"] = round(float(f[up].mean()) * 100, 3)
        out["fwd_down_mean_pct"] = round(float(f[~up].mean()) * 100, 3)
        out["trend_premium_pct"] = round(float(f[up].mean() - f[~up].mean()) * 100, 3)
    return out


def horizon_frame(panel: pd.DataFrame, h: int) -> pd.DataFrame:
    """Filas no solapadas (paso h por símbolo) con past/fwd de h días y vol tercil."""
    rows: list[pd.DataFrame] = []
    for _, g in panel.groupby("symbol", observed=True):
        g = g.sort_values("ts").reset_index(drop=True)
        close = g["close"]
        past = close / close.shift(h) - 1
        fwd = close.shift(-h) / close - 1
        rv = close.pct_change().rolling(VOL_WINDOW).std()
        sub = pd.DataFrame({"ts": g["ts"], "past": past, "fwd": fwd, "rv": rv}).iloc[h::h]
        rows.append(sub)
    out = pd.concat(rows, ignore_index=True).dropna(subset=["past", "fwd"])
    out["year"] = pd.to_datetime(out["ts"]).dt.year
    # terciles por rank pct (robusto a empates/constantes, donde qcut truena)
    r = out["rv"].rank(pct=True)
    out["vol_terc"] = pd.cut(
        r, [0.0, 1 / 3, 2 / 3, 1.0], labels=["baja", "media", "alta"], include_lowest=True
    )
    return out


def study(panel: pd.DataFrame) -> dict[str, Any]:
    per_h: dict[str, Any] = {}
    for h in HORIZONS:
        df = horizon_frame(panel, h)
        entry: dict[str, Any] = {"pooled": _sign_stats(df["past"], df["fwd"])}
        entry["by_year"] = {str(y): _sign_stats(g["past"], g["fwd"]) for y, g in df.groupby("year")}
        entry["by_vol"] = {
            str(v): _sign_stats(g["past"], g["fwd"])
            for v, g in df.groupby("vol_terc", observed=True)
        }
        per_h[str(h)] = entry
    return per_h


def main() -> int:
    from src.lab.train import load_panel

    panel = load_panel(1)
    per_h = study(panel)

    report = {
        "generated": datetime.now(UTC).isoformat(),
        "protocol": {"horizons": HORIZONS, "vol_window": VOL_WINDOW, "step": "no-overlap h"},
        "per_horizon": per_h,
    }
    gcs.upload_json(report, "reports/trend_study_h13.json")

    lines = [
        "# Estructura de tendencia H13 §5b\n",
        "Prima de tendencia = E[fwd_H | past_H>0] − E[fwd_H | past_H<0], sin costos.\n",
        "| H (días) | n | persistencia | prima (%) | prima vol baja | vol media | vol alta |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in HORIZONS:
        e = per_h[str(h)]
        p = e["pooled"]
        if "persistence" not in p:
            continue
        by_v = e["by_vol"]
        cells = [
            f"{by_v.get(v, {}).get('trend_premium_pct', float('nan')):+.2f}"
            for v in ("baja", "media", "alta")
        ]
        lines.append(
            f"| {h} | {p['n']} | {p['persistence']:.3f} | {p['trend_premium_pct']:+.2f} "
            f"| {cells[0]} | {cells[1]} | {cells[2]} |"
        )
        print(
            f"[trend] H={h}: n={p['n']} persist={p['persistence']:.3f} "
            f"prima={p['trend_premium_pct']:+.2f}%"
        )
    gcs.upload_text("\n".join(lines), "reports/trend_study_h13.md")
    return 0


__all__ = ["HORIZONS", "horizon_frame", "study"]

if __name__ == "__main__":
    sys.exit(main())
