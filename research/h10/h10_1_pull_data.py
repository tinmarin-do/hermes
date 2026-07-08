"""H10.1 — Pull de datos públicos: funding rates (perps Binance) + taker buy volume (klines spot).

Pilot-first (pre-registro H10.1): los datos van a un DuckDB de RESEARCH separado
(`research/h10/h10_data.duckdb`) — el medallón de producción NO se toca. La ingesta
formal a src/ solo se construye si H10.1 pasa. APIs públicas, $0, sin keys.

Rango: 2021-01-01 → 2025-07-05 (buffer sobre la ventana de iteración 2025-06-28).
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime

import ccxt
import duckdb

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "LINK/USDT", "AVAX/USDT", "XRP/USDT"]
SINCE = int(datetime(2021, 1, 1, tzinfo=UTC).timestamp() * 1000)
UNTIL_MS = int(datetime(2025, 7, 5, tzinfo=UTC).timestamp() * 1000)
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "h10_data.duckdb")


def pull_funding(con: duckdb.DuckDBPyConnection) -> None:
    ex = ccxt.binanceusdm({"enableRateLimit": True})
    con.execute(
        "CREATE TABLE IF NOT EXISTS h10_funding (symbol VARCHAR, ts TIMESTAMP, rate DOUBLE,"
        " PRIMARY KEY (symbol, ts))"
    )
    for sym in SYMBOLS:
        perp = f"{sym}:USDT"
        since = SINCE
        n = 0
        while since < UNTIL_MS:
            try:
                rows = ex.fetch_funding_rate_history(perp, since=since, limit=1000)
            except Exception as e:  # símbolo sin perp en parte del rango, red, etc.
                print(f"  {sym}: stop en {since} ({type(e).__name__}: {e})", file=sys.stderr)
                break
            if not rows:
                break
            for r in rows:
                ts = datetime.fromtimestamp(r["timestamp"] / 1000, tz=UTC).replace(tzinfo=None)
                con.execute(
                    "INSERT OR REPLACE INTO h10_funding VALUES (?, ?, ?)",
                    [sym, ts, float(r["fundingRate"])],
                )
            n += len(rows)
            last = rows[-1]["timestamp"]
            if last <= since:
                break
            since = last + 1
        print(f"funding {sym}: {n} filas", file=sys.stderr)


def pull_taker(con: duckdb.DuckDBPyConnection) -> None:
    ex = ccxt.binance({"enableRateLimit": True})
    con.execute(
        "CREATE TABLE IF NOT EXISTS h10_taker (symbol VARCHAR, ts TIMESTAMP,"
        " volume DOUBLE, taker_buy DOUBLE, PRIMARY KEY (symbol, ts))"
    )
    for sym in SYMBOLS:
        market_id = sym.replace("/", "")
        since = SINCE
        n = 0
        while since < UNTIL_MS:
            kl = ex.public_get_klines(
                {"symbol": market_id, "interval": "1h", "startTime": since, "limit": 1000}
            )
            if not kl:
                break
            for k in kl:
                ts = datetime.fromtimestamp(int(k[0]) / 1000, tz=UTC).replace(tzinfo=None)
                con.execute(
                    "INSERT OR REPLACE INTO h10_taker VALUES (?, ?, ?, ?)",
                    [sym, ts, float(k[5]), float(k[9])],  # volume, takerBuyBase
                )
            n += len(kl)
            last = int(kl[-1][0])
            if last <= since:
                break
            since = last + 3_600_000
            time.sleep(0.05)
        print(f"taker {sym}: {n} filas", file=sys.stderr)


def main() -> None:
    con = duckdb.connect(DB)
    try:
        pull_funding(con)
        pull_taker(con)
        for t in ("h10_funding", "h10_taker"):
            for row in con.execute(
                f"SELECT symbol, MIN(ts), MAX(ts), COUNT(*) FROM {t} GROUP BY symbol ORDER BY symbol"
            ).fetchall():
                print(t, row)
    finally:
        con.close()


if __name__ == "__main__":
    main()
