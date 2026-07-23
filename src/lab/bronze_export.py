"""Convierte el snapshot DuckDB (subido por el cable local) a parquet por símbolo.

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.bronze_export"
Lee  gs://<bucket>/bronze/hermes_snapshot_YYYYMMDD.duckdb  (el más reciente)
Escribe gs://<bucket>/bronze/binance_ohlcv_1h/<SYMBOL>.parquet + data_quality parcial.
"""

import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from src.lab import gcs


def main() -> int:
    snapshots = sorted(gcs.list_blobs("bronze/hermes_snapshot_"))
    if not snapshots:
        print("ERROR: no hay snapshot DuckDB en bronze/")
        return 1
    snap = snapshots[-1]
    workdir = tempfile.mkdtemp(prefix="lab-export-")
    local = gcs.download_to(snap, Path(workdir) / "snapshot.duckdb")
    print(f"[export] usando {snap}")

    con = duckdb.connect(str(local), read_only=True)
    symbols = [
        r[0]
        for r in con.execute(
            "select distinct symbol from bronze_ohlcv where timeframe='1h' order by symbol"
        ).fetchall()
    ]

    quality = {}
    for sym in symbols:
        df = con.execute(
            """select ts, open, high, low, close, volume from bronze_ohlcv
               where symbol = ? and timeframe = '1h' order by ts""",
            [sym],
        ).df()
        gcs.upload_parquet(df, f"bronze/binance_ohlcv_1h/{gcs.safe_name(sym)}.parquet")
        expected = int((df.ts.max() - df.ts.min()).total_seconds() // 3600) + 1
        quality[sym] = {
            "rows": len(df),
            "dups": int(len(df) - df.ts.nunique()),
            "gaps": int(expected - df.ts.nunique()),
            "from": str(df.ts.min()),
            "to": str(df.ts.max()),
        }
        print(f"  {sym:14s} {len(df):>7,} filas → parquet")
    con.close()

    gcs.upload_json(
        {"source": "binance", "exported_at": datetime.now(UTC).isoformat(), "symbols": quality},
        "reports/data_quality_binance.json",
    )
    print(f"[export] {len(symbols)} símbolos exportados + reports/data_quality_binance.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
