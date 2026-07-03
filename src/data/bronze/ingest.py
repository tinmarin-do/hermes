"""Pull OHLCV from ccxt and store in DuckDB Bronze layer."""

import os
import time
from datetime import UTC, datetime

import ccxt
import pandas as pd

from src.data.db import get_connection

BATCH_SIZE = 1000  # candles per ccxt request
RATE_LIMIT_SLEEP = 0.5  # seconds between requests

# Bitso no lista LINK/AVAX contra USDT — se ingesta el par /USD (basis USD≈USDT
# <0.1% típico, negligible para señales de momentum multi-día).
BITSO_PAIR_MAP = {"LINK/USDT": "LINK/USD", "AVAX/USDT": "AVAX/USD"}


def ingest(symbol: str, timeframe: str, since: datetime, until: datetime) -> int:
    """Fetch OHLCV for symbol/timeframe between since and until. Returns row count.

    Fuente configurable vía DATA_EXCHANGE_ID: `binance` (default — historia local)
    o `bitso` (cloud: Binance geo-bloquea IPs de GCP con HTTP 451; Bitso es además
    el venue de ejecución — se mide donde se opera). Las filas se guardan SIEMPRE
    bajo el símbolo canónico (p. ej. LINK/USDT) para continuidad de la serie.
    """
    ex_id = os.environ.get("DATA_EXCHANGE_ID", "binance")
    exchange = getattr(ccxt, ex_id)({"enableRateLimit": True})
    fetch_symbol = BITSO_PAIR_MAP.get(symbol, symbol) if ex_id == "bitso" else symbol

    since_ms = int(since.timestamp() * 1000)
    until_ms = int(until.timestamp() * 1000)

    all_candles: list[list] = []
    cursor = since_ms

    while cursor < until_ms:
        candles = exchange.fetch_ohlcv(fetch_symbol, timeframe, since=cursor, limit=BATCH_SIZE)
        if not candles:
            break

        # filter to requested range
        candles = [c for c in candles if c[0] < until_ms]
        if not candles:
            break
        all_candles.extend(candles)

        last_ts = candles[-1][0]
        if last_ts <= cursor:
            break
        cursor = last_ts + 1

        if len(candles) == BATCH_SIZE:
            time.sleep(RATE_LIMIT_SLEEP)

    if not all_candles:
        return 0

    df = pd.DataFrame(all_candles, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_localize(None)
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df["ingested_at"] = datetime.now(UTC).replace(tzinfo=None)
    df = df.drop_duplicates(subset=["ts"])

    con = get_connection()
    con.execute(
        "DELETE FROM bronze_ohlcv WHERE symbol = ? AND timeframe = ? AND ts >= ? AND ts <= ?",
        [symbol, timeframe, since.replace(tzinfo=None), until.replace(tzinfo=None)],
    )
    con.execute("""
        INSERT INTO bronze_ohlcv (symbol, timeframe, ts, open, high, low, close, volume, ingested_at)
        SELECT symbol, timeframe, ts, open, high, low, close, volume, ingested_at FROM df
    """)
    con.close()
    return len(df)
