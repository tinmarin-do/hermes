"""Dataset builder H11 — spine diario pooled + label MXN (pre-registro en DESIGN_H11).

Resampleo 1h→diario anclado a 00:00 UTC: la barra del día D cubre [D 00:00, D+1 00:00).
Label (SIEMPRE en MXN, umbral +1%):
  binance:  y(D) = 1  si  (1+r_usdt)(1+r_fx) − 1 > 0.01,  r sobre closes D→D+1
  bitso:    y(D) = 1  si  close_mxn(D+1)/close_mxn(D) − 1 > 0.01  (nativo)

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.dataset"
Escribe datasets/daily_v1.parquet + reports/base_rates.md
"""

import sys
from datetime import UTC, datetime

import pandas as pd

from src.lab import gcs

LABEL_THRESHOLD = 0.01
DELISTED = {"EOS", "FTM", "MKR", "MATIC"}  # en corpus (anti-supervivencia), no operables
# Libros FX/stablecoin de Bitso: son series de referencia (FX del venue), NO objetivos
# de inversión — base rate 3-11% (verificado en base_rates 2026-07-11) contaminaría
# el pooled. Se quedan en el dataset (features) pero operable=False.
NON_TARGET = {"EUR", "USD", "USDT", "USDS", "TUSD", "PYUSD", "RLUSD"}


def _daily_bars(df: pd.DataFrame) -> pd.DataFrame:
    d = df.set_index("ts").sort_index()
    bars = pd.DataFrame(
        {
            "open": d["open"].resample("1D").first(),
            "high": d["high"].resample("1D").max(),
            "low": d["low"].resample("1D").min(),
            "close": d["close"].resample("1D").last(),
            "volume": d["volume"].resample("1D").sum(),
            "n_candles": d["close"].resample("1D").count(),
        }
    )
    # una barra diaria construida con menos de 20/24 velas es sospechosa → fuera
    return bars[bars.n_candles >= 20].drop(columns="n_candles").dropna()


def _label_frame(bars: pd.DataFrame, fx_ret: pd.Series | None) -> pd.DataFrame:
    r = bars["close"].pct_change().shift(-1)  # retorno D→D+1 visto desde D
    if fx_ret is not None:
        r_fx_fwd = fx_ret.shift(-1).reindex(bars.index).fillna(0.0)
        r = (1 + r) * (1 + r_fx_fwd) - 1
    out = bars.copy()
    out["fwd_ret_24h_mxn"] = r
    out["y"] = (r > LABEL_THRESHOLD).astype("float")
    return out.dropna(subset=["fwd_ret_24h_mxn"])


def main() -> int:
    fx = gcs.read_parquet("fx/usdmxn.parquet").set_index("date")["usdmxn"]
    fx_ret = fx.pct_change()

    frames = []
    for blob in sorted(gcs.list_blobs("bronze/binance_ohlcv_1h/")):
        pair = blob.split("/")[-1].removesuffix(".parquet").replace("_", "/")
        base = pair.split("/")[0]
        bars = _label_frame(_daily_bars(gcs.read_parquet(blob)), fx_ret)
        bars["source"], bars["symbol"], bars["pair"] = "binance", base, pair
        bars["operable"] = base not in DELISTED
        frames.append(bars.reset_index().rename(columns={"index": "ts"}))

    for blob in sorted(gcs.list_blobs("bronze/bitso_ohlcv_1h/")):
        pair = blob.split("/")[-1].removesuffix(".parquet").replace("_", "/")
        base = pair.split("/")[0]
        bars = _label_frame(_daily_bars(gcs.read_parquet(blob)), fx_ret=None)
        bars["source"], bars["symbol"], bars["pair"] = "bitso", base, pair
        bars["operable"] = base not in NON_TARGET
        frames.append(bars.reset_index().rename(columns={"index": "ts"}))

    if not frames:
        print("ERROR: sin data en bronze/")
        return 1
    full = pd.concat(frames, ignore_index=True).sort_values(["source", "symbol", "ts"])
    gcs.upload_parquet(full, "datasets/daily_v1.parquet")

    # base rates por fuente/símbolo/año + floor del F1 naive (todo-positivo)
    full["year"] = pd.to_datetime(full.ts).dt.year
    lines = [
        "# Base rates del target y=1 (ret 24h MXN > +1%) — arco H11",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · dataset daily_v1 ({len(full):,} filas)\n",
        "F1 naive (siempre-sí) = 2p/(1+p). La meta F1≥0.60 exige superar este floor.\n",
        "| fuente | símbolo | filas | p(y=1) | F1 naive |",
        "|---|---|---|---|---|",
    ]
    grp = full.groupby(["source", "symbol"])["y"].agg(["count", "mean"])
    for (src, sym), row in grp.iterrows():
        p = row["mean"]
        lines.append(f"| {src} | {sym} | {int(row['count']):,} | {p:.1%} | {2 * p / (1 + p):.3f} |")
    p_all = full["y"].mean()
    f1_naive = 2 * p_all / (1 + p_all)
    lines.append(f"| **pooled** | — | {len(full):,} | {p_all:.1%} | {f1_naive:.3f} |")
    gcs.upload_text("\n".join(lines), "reports/base_rates.md")

    print(f"[dataset] {len(full):,} filas → datasets/daily_v1.parquet")
    print(f"[dataset] base rate pooled p={p_all:.3f} · F1 naive={2 * p_all / (1 + p_all):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
