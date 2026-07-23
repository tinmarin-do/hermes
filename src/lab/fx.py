"""Serie USDMXN diaria → fx/usdmxn.parquet (label MXN del corpus Binance).

Fuente v1: FRED DEXMXUS vía CSV público (sin API key — desbloquea el arco hoy).
Banxico SIE SF43718 (FIX) queda como upgrade opcional cuando haya token.
Forward-fill de fines de semana/feriados: cripto opera 7d, el FIX no.
"""

import io
import sys
from datetime import UTC, datetime

import httpx
import pandas as pd

from src.lab import gcs

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXMXUS"


def main() -> int:
    r = httpx.get(FRED_CSV, timeout=60, follow_redirects=True)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "usdmxn"]
    df["date"] = pd.to_datetime(df["date"])
    df["usdmxn"] = pd.to_numeric(df["usdmxn"], errors="coerce")
    df = df[df.date >= "2020-12-01"].set_index("date")

    # calendario diario completo + forward-fill (fines de semana/feriados)
    full = df.reindex(pd.date_range(df.index.min(), datetime.now(UTC).date(), freq="D"))
    full["usdmxn"] = full["usdmxn"].ffill()
    full = full.rename_axis("date").reset_index()

    gcs.upload_parquet(full, "fx/usdmxn.parquet")
    last = full.dropna().iloc[-1]
    print(f"[fx] {len(full)} días → fx/usdmxn.parquet")
    print(f"[fx] último dato: {last.date:%Y-%m-%d} = {last.usdmxn:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
