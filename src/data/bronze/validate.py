"""Validate integrity of Bronze OHLCV data."""

from dataclasses import dataclass

import pandas as pd

from src.data.db import get_connection

TIMEFRAME_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
MAX_GAP_MULTIPLIER = 3  # alert if gap > 3× expected interval


@dataclass
class BronzeValidationResult:
    ok: bool
    rows: int
    since: str
    until: str
    gaps: int
    nulls: int
    errors: list[str]


def validate(symbol: str, timeframe: str) -> BronzeValidationResult:
    con = get_connection()
    df = con.execute(
        "SELECT * FROM bronze_ohlcv WHERE symbol = ? AND timeframe = ? ORDER BY ts",
        [symbol, timeframe],
    ).df()
    con.close()

    errors: list[str] = []

    if df.empty:
        return BronzeValidationResult(False, 0, "—", "—", 0, 0, ["No data found"])

    # null check
    nulls = int(df[["open", "high", "low", "close", "volume"]].isnull().sum().sum())
    if nulls > 0:
        errors.append(f"{nulls} null values in OHLCV columns")

    # OHLC sanity
    bad_hl = (df["high"] < df["low"]).sum()
    if bad_hl > 0:
        errors.append(f"{bad_hl} rows where high < low")

    bad_close = ((df["close"] < df["low"]) | (df["close"] > df["high"])).sum()
    if bad_close > 0:
        errors.append(f"{bad_close} rows where close outside [low, high]")

    # gap detection
    interval_min = TIMEFRAME_MINUTES.get(timeframe, 60)
    expected_delta = pd.Timedelta(minutes=interval_min)
    threshold = expected_delta * MAX_GAP_MULTIPLIER
    deltas = df["ts"].diff().dropna()
    gaps = int((deltas > threshold).sum())
    if gaps > 0:
        errors.append(f"{gaps} time gaps larger than {MAX_GAP_MULTIPLIER}× expected interval")

    return BronzeValidationResult(
        ok=len(errors) == 0,
        rows=len(df),
        since=str(df["ts"].min()),
        until=str(df["ts"].max()),
        gaps=gaps,
        nulls=nulls,
        errors=errors,
    )
