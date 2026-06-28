"""Compute Silver features: returns, Hurst, GARCH vol, spread, regime."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from arch import arch_model
from hurst import compute_Hc

from src.data.db import get_connection

HURST_WINDOW = 200   # minimum rows for a meaningful Hurst estimate
GARCH_WINDOW = 500   # rows used to fit each GARCH model
MIN_ROWS = 100       # skip symbol if fewer rows available


def _classify_regime(h: float) -> tuple[str, float]:
    if h > 0.55:
        return "trending", round((h - 0.55) / 0.45, 3)
    if h < 0.45:
        return "mean_reverting", round((0.45 - h) / 0.45, 3)
    return "random_walk", round(1 - abs(h - 0.5) / 0.05, 3)


def _rolling_hurst(closes: pd.Series, window: int) -> pd.Series:
    result = pd.Series(np.nan, index=closes.index)
    for i in range(window, len(closes) + 1):
        chunk = closes.iloc[i - window:i].values
        try:
            h, _, _ = compute_Hc(chunk, kind="price", simplified=True)
            result.iloc[i - 1] = h
        except Exception:
            pass
    return result


def _rolling_garch_vol(log_returns: pd.Series, window: int) -> pd.Series:
    result = pd.Series(np.nan, index=log_returns.index)
    for i in range(window, len(log_returns) + 1):
        chunk = log_returns.iloc[i - window:i].dropna()
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
    df["returns"] = df["close"].pct_change()
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
    df["spread"] = (df["high"] - df["low"]) / df["close"]

    df["hurst"] = _rolling_hurst(df["close"], HURST_WINDOW)
    df["garch_vol"] = _rolling_garch_vol(df["log_returns"], GARCH_WINDOW)

    df[["regime", "regime_conf"]] = df["hurst"].apply(
        lambda h: pd.Series(_classify_regime(h)) if pd.notna(h) else pd.Series([None, None])
    )

    df = df.reset_index()
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df["computed_at"] = datetime.now(timezone.utc).replace(tzinfo=None)

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
