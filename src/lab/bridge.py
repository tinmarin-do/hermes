"""Puente de tracking Binance↔Bitso (pre-registrado, arco H11).

Por cada libro Bitso con par gemelo en Binance, sobre el traslape diario:
  r_bitso_mxn  vs  r_binance_mxn = (1+r_usdt)(1+r_usdmxn)−1
Métricas: correlación, error mediano |Δr|, tracking error (std Δr).
Umbral de aceptación pre-registrado: mediana |Δr| ≤ 30 bps y corr ≥ 0.95 →
lo entrenado en Binance transfiere; si un libro sale fuera, se reporta a Erika.

Salida: reports/venue_bridge.md + .json
"""

import sys
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from src.lab import gcs

THRESH_MEDIAN_BPS = 30.0
THRESH_CORR = 0.95


def _daily_close(df: pd.DataFrame) -> pd.Series:
    d = df.set_index("ts").sort_index()
    return d["close"].resample("1D").last().dropna()


def main() -> int:
    fx = gcs.read_parquet("fx/usdmxn.parquet").set_index("date")["usdmxn"]
    r_fx = fx.pct_change()

    bitso_blobs = gcs.list_blobs("bronze/bitso_ohlcv_1h/")
    binance_blobs = set(gcs.list_blobs("bronze/binance_ohlcv_1h/"))

    rows = []
    for blob in sorted(bitso_blobs):
        book = blob.split("/")[-1].removesuffix(".parquet")  # p.ej. BTC_MXN
        base = book.split("_")[0]
        twin = f"bronze/binance_ohlcv_1h/{base}_USDT.parquet"
        if twin not in binance_blobs:
            continue
        r_bitso = _daily_close(gcs.read_parquet(blob)).pct_change()
        r_usdt = _daily_close(gcs.read_parquet(twin)).pct_change()
        df = pd.concat(
            {"bitso": r_bitso, "usdt": r_usdt, "fx": r_fx}, axis=1, join="inner"
        ).dropna()
        if len(df) < 60:
            rows.append({"book": book, "days": len(df), "verdict": "TRASLAPE_INSUFICIENTE"})
            continue
        binance_mxn = (1 + df.usdt) * (1 + df.fx) - 1
        delta = df.bitso - binance_mxn
        med_bps = float(delta.abs().median() * 1e4)
        te_bps = float(delta.std() * 1e4)
        corr = float(np.corrcoef(df.bitso, binance_mxn)[0, 1])
        ok = med_bps <= THRESH_MEDIAN_BPS and corr >= THRESH_CORR
        rows.append(
            {
                "book": book,
                "days": len(df),
                "median_abs_bps": round(med_bps, 1),
                "tracking_err_bps": round(te_bps, 1),
                "corr": round(corr, 4),
                "verdict": "TRANSFIERE" if ok else "REVISAR_CON_ERIKA",
            }
        )

    lines = [
        "# Puente de tracking Binance↔Bitso — arco H11",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · retornos DIARIOS del traslape",
        f"Umbral pre-registrado: mediana |Δr| ≤ {THRESH_MEDIAN_BPS:.0f} bps "
        f"y corr ≥ {THRESH_CORR}\n",
        "| libro | días | mediana \\|Δr\\| (bps) | TE (bps) | corr | veredicto |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['book']} | {r['days']} | {r.get('median_abs_bps', '—')} "
            f"| {r.get('tracking_err_bps', '—')} | {r.get('corr', '—')} | {r['verdict']} |"
        )
        print(f"  {r['book']:12s} {r['verdict']}")
    gcs.upload_text("\n".join(lines), "reports/venue_bridge.md")
    gcs.upload_json(rows, "reports/venue_bridge.json")
    print("[bridge] → reports/venue_bridge.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
