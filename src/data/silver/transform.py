"""Compute Silver features: returns, Hurst, GARCH vol, spread, regime."""

from datetime import UTC, datetime

import numpy as np
import pandas as pd
from arch import arch_model
from hurst import compute_Hc

from src.data.db import get_connection

HURST_WINDOW = 200  # minimum rows for a meaningful Hurst estimate
GARCH_WINDOW = 500  # rows used to fit each GARCH model
MIN_ROWS = 100  # skip symbol if fewer rows available


def _classify_regime(h: float) -> tuple[str, float]:
    if h > 0.55:
        return "trending", round((h - 0.55) / 0.45, 3)
    if h < 0.45:
        return "mean_reverting", round((0.45 - h) / 0.45, 3)
    return "random_walk", round(1 - abs(h - 0.5) / 0.05, 3)


def _rolling_hurst(closes: pd.Series, window: int) -> pd.Series:
    result = pd.Series(np.nan, index=closes.index)
    for i in range(window, len(closes) + 1):
        chunk = closes.iloc[i - window : i].values
        try:
            h, _, _ = compute_Hc(chunk, kind="price", simplified=True)
            result.iloc[i - 1] = h
        except Exception:
            pass
    return result


def _rolling_garch_vol(log_returns: pd.Series, window: int) -> pd.Series:
    result = pd.Series(np.nan, index=log_returns.index)
    for i in range(window, len(log_returns) + 1):
        chunk = log_returns.iloc[i - window : i].dropna()
        if len(chunk) < 50:
            continue
        try:
            model = arch_model(chunk * 100, vol="Garch", p=1, q=1, rescale=False)
            fit = model.fit(disp="off", show_warning=False)
            result.iloc[i - 1] = fit.conditional_volatility.iloc[-1] / 100
        except Exception:
            pass
    return result


def transform(symbol: str, timeframe: str) -> int:
    """Compute Silver features from Bronze data. Returns row count written."""
    con = get_connection()
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM bronze_ohlcv "
        "WHERE symbol = ? AND timeframe = ? ORDER BY ts",
        [symbol, timeframe],
    ).df()

    if len(df) < MIN_ROWS:
        con.close()
        raise ValueError(f"Not enough Bronze rows ({len(df)}) for {symbol} {timeframe}")

    df = df.set_index("ts").sort_index()
    df = _compute_features(df)
    df = df.reset_index()
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df["computed_at"] = datetime.now(UTC).replace(tzinfo=None)

    con.execute(
        "DELETE FROM silver_features WHERE symbol = ? AND timeframe = ?",
        [symbol, timeframe],
    )
    con.execute("""
        INSERT INTO silver_features
            (symbol, timeframe, ts, close, returns, log_returns, hurst,
             garch_vol, spread, regime, regime_conf, computed_at)
        SELECT symbol, timeframe, ts, close, returns, log_returns, hurst,
               garch_vol, spread, regime, regime_conf, computed_at
        FROM df
    """)
    con.close()
    return len(df)


def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features rolling sobre un frame de bronze indexado por ts (compartido full/tail)."""
    df["returns"] = df["close"].pct_change()
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
    df["spread"] = (df["high"] - df["low"]) / df["close"]
    df["hurst"] = _rolling_hurst(df["close"], HURST_WINDOW)
    df["garch_vol"] = _rolling_garch_vol(df["log_returns"], GARCH_WINDOW)
    df[["regime", "regime_conf"]] = df["hurst"].apply(
        lambda h: pd.Series(_classify_regime(h)) if pd.notna(h) else pd.Series([None, None])
    )
    return df


def transform_tail(symbol: str, timeframe: str, tail_hours: int = 48) -> int:
    """Silver INCREMENTAL — recomputa solo el tramo final (refresh diario, PRD §8.8).

    Carga tail + contexto de warmup (GARCH 500h + margen) desde bronze, computa las
    mismas features rolling y upserta SOLO las filas nuevas/solapadas. El recompute
    completo (~13 min/símbolo) queda para backfills; esto tarda ~1 min/símbolo.
    Sin Silver previo → cae al transform() completo.
    """
    from datetime import timedelta

    con = get_connection()
    last = con.execute(
        "SELECT max(ts) FROM silver_features WHERE symbol = ? AND timeframe = ?",
        [symbol, timeframe],
    ).fetchone()[0]
    if last is None:
        con.close()
        return transform(symbol, timeframe)

    cutoff = last - timedelta(hours=tail_hours)  # solapa el final ya computado
    context_start = cutoff - timedelta(hours=GARCH_WINDOW + 50)

    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM bronze_ohlcv "
        "WHERE symbol = ? AND timeframe = ? AND ts >= ? ORDER BY ts",
        [symbol, timeframe, context_start],
    ).df()
    if len(df) < MIN_ROWS:
        con.close()
        raise ValueError(f"Not enough Bronze context rows ({len(df)}) for {symbol} tail")

    df = df.set_index("ts").sort_index()
    df = _compute_features(df)
    df = df.reset_index()

    new = df[df["ts"] > cutoff].copy()
    if new.empty:
        con.close()
        return 0
    new["symbol"] = symbol
    new["timeframe"] = timeframe
    new["computed_at"] = datetime.now(UTC).replace(tzinfo=None)

    con.register("new_rows", new)
    con.execute("""
        INSERT OR REPLACE INTO silver_features
            (symbol, timeframe, ts, close, returns, log_returns, hurst,
             garch_vol, spread, regime, regime_conf, computed_at)
        SELECT symbol, timeframe, ts, close, returns, log_returns, hurst,
               garch_vol, spread, regime, regime_conf, computed_at
        FROM new_rows
    """)
    con.close()
    return len(new)
