"""Aggregate Silver features into Gold signals ready for agents.

Produces one RegimeSignal per symbol — the only input agents receive.
News features (cluster, sentiment, trust) are injected from silver_news_clusters.
"""

import json
import os
from datetime import UTC, datetime

from src.data.db import get_connection

REGIME_MAP = {
    "trending": "trending",
    "mean_reverting": "mean-reverting",
    "random_walk": "volatile",
}

BULLISH_CLUSTERS = {"protocol_upgrade", "listing", "adoption", "partnership"}
BEARISH_CLUSTERS = {"regulatory", "hack"}


def _news_context(con, symbol: str) -> dict | None:
    """Aggregate news features for a symbol from silver_news_clusters.

    Returns {news_cluster, news_sentiment_score, trust_score, dominant_cluster_count}
    or None if no news data exists for this symbol.
    """
    base = symbol.split("/")[0].upper()
    try:
        row = con.execute(
            """
            WITH sym_news AS (
                SELECT snc.cluster_label, snc.trust_score
                FROM silver_news_clusters snc
                JOIN bronze_news bn ON bn.id = snc.id AND bn.source = snc.source
                WHERE snc.is_noise = FALSE
                  AND snc.cluster_label IS NOT NULL
                  AND bn.symbols LIKE '%\"' || ? || '\"%'
            ),
            dominant AS (
                SELECT
                    cluster_label,
                    COUNT(*) AS cnt,
                    AVG(COALESCE(trust_score, 0.5)) AS avg_trust
                FROM sym_news
                GROUP BY cluster_label
                ORDER BY cnt DESC
                LIMIT 1
            )
            SELECT
                d.cluster_label AS news_cluster,
                d.cnt AS dominant_count,
                d.avg_trust AS trust_score,
                (SELECT AVG(COALESCE(trust_score, 0.5)) FROM sym_news) AS avg_trust_all
            FROM dominant d
        """,
            [base],
        ).fetchone()

        if row is None:
            return None

        cluster_label = row[0]
        trust_score = round(float(row[2] or 0.5), 4)

        sentiment = 0.0
        if cluster_label in BULLISH_CLUSTERS:
            sentiment = 0.6
        elif cluster_label in BEARISH_CLUSTERS:
            sentiment = -0.4

        return {
            "news_cluster": cluster_label,
            "news_sentiment_score": sentiment,
            "trust_score": trust_score,
            "dominant_cluster_count": row[1],
        }
    except Exception:
        return None


def _regime_signal(row: dict, news: dict | None) -> dict:
    """Build RegimeSignal JSON matching the agent contract schema."""
    features = {
        "hurst": round(float(row["hurst"]), 4) if row["hurst"] is not None else None,
        "garch_vol": round(float(row["garch_vol"]), 6) if row["garch_vol"] is not None else None,
        "spread": round(float(row["spread"]), 6) if row["spread"] is not None else None,
        "returns_1h": round(float(row["returns_1h"]), 6) if row["returns_1h"] is not None else None,
        "returns_24h": round(float(row["returns_24h"]), 6)
        if row["returns_24h"] is not None
        else None,
    }

    if news is not None:
        features["news_cluster"] = news["news_cluster"]
        features["news_sentiment_score"] = news["news_sentiment_score"]
        features["trust_score"] = news["trust_score"]
        features["dominant_cluster_count"] = news["dominant_cluster_count"]

    return {
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "ts": row["ts"].isoformat() if hasattr(row["ts"], "isoformat") else str(row["ts"]),
        "regime": REGIME_MAP.get(row["regime"], "volatile"),
        "regime_conf": round(float(row["regime_conf"] or 0), 4),
        "features": features,
        "context": {
            "hermes_mode": os.environ.get("HERMES_MODE", "local"),
            "exchange_mode": os.environ.get("EXCHANGE_MODE", "paper"),
        },
    }


def aggregate(symbols: list[str], timeframe: str = "1h") -> list[dict]:
    """Produce Gold signals for given symbols. Returns list of RegimeSignal dicts."""
    con = get_connection()
    results = []

    for symbol in symbols:
        row = con.execute(
            """
            WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY ts DESC) AS rn
                FROM silver_features
                WHERE symbol = ? AND timeframe = ? AND regime IS NOT NULL
            ),
            returns AS (
                SELECT
                    ts,
                    returns AS returns_1h,
                    SUM(returns) OVER (
                        ORDER BY ts
                        ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
                    ) AS returns_24h
                FROM silver_features
                WHERE symbol = ? AND timeframe = ?
                ORDER BY ts DESC
                LIMIT 25
            )
            SELECT
                l.symbol, l.timeframe, l.ts, l.regime, l.regime_conf,
                l.hurst, l.garch_vol, l.spread,
                r.returns_1h, r.returns_24h
            FROM latest l
            LEFT JOIN returns r ON l.ts = r.ts
            WHERE l.rn = 1
        """,
            [symbol, timeframe, symbol, timeframe],
        ).fetchone()

        if row is None:
            continue

        cols = [
            "symbol",
            "timeframe",
            "ts",
            "regime",
            "regime_conf",
            "hurst",
            "garch_vol",
            "spread",
            "returns_1h",
            "returns_24h",
        ]
        row_dict = dict(zip(cols, row))
        news = _news_context(con, symbol)
        signal = _regime_signal(row_dict, news)

        computed_at = datetime.now(UTC).replace(tzinfo=None)
        con.execute(
            """
            INSERT OR REPLACE INTO gold_signals
                (symbol, timeframe, ts, regime, regime_conf, hurst, garch_vol,
                 spread, returns_1h, returns_24h, signal_json, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            [
                symbol,
                timeframe,
                row_dict["ts"],
                signal["regime"],
                signal["regime_conf"],
                row_dict["hurst"],
                row_dict["garch_vol"],
                row_dict["spread"],
                row_dict["returns_1h"],
                row_dict["returns_24h"],
                json.dumps(signal),
                computed_at,
            ],
        )

        results.append(signal)

    con.close()
    return results


def aggregate_at(symbols: list[str], timeframe: str, as_of_ts: datetime) -> list[dict]:
    """Produce Gold signals as they would have been at a historical timestamp."""
    con = get_connection()
    results = []

    for symbol in symbols:
        row = con.execute(
            """
            WITH at_point AS (
                SELECT *, ROW_NUMBER() OVER (ORDER BY ts DESC) AS rn
                FROM silver_features
                WHERE symbol = ? AND timeframe = ?
                  AND ts <= ?
                  AND regime IS NOT NULL
            ),
            returns AS (
                SELECT
                    ts,
                    returns AS returns_1h,
                    SUM(returns) OVER (
                        ORDER BY ts
                        ROWS BETWEEN 23 PRECEDING AND CURRENT ROW
                    ) AS returns_24h
                FROM silver_features
                WHERE symbol = ? AND timeframe = ?
                  AND ts <= ?
                ORDER BY ts DESC
                LIMIT 25
            )
            SELECT
                a.symbol, a.timeframe, a.ts, a.regime, a.regime_conf,
                a.hurst, a.garch_vol, a.spread,
                r.returns_1h, r.returns_24h
            FROM at_point a
            LEFT JOIN returns r ON a.ts = r.ts
            WHERE a.rn = 1
        """,
            [symbol, timeframe, as_of_ts, symbol, timeframe, as_of_ts],
        ).fetchone()

        if row is None:
            continue

        cols = [
            "symbol",
            "timeframe",
            "ts",
            "regime",
            "regime_conf",
            "hurst",
            "garch_vol",
            "spread",
            "returns_1h",
            "returns_24h",
        ]
        row_dict = dict(zip(cols, row))
        news = _news_context(con, symbol)
        signal = _regime_signal(row_dict, news)
        results.append(signal)

    con.close()
    return results


def get_available_period(symbol: str, timeframe: str) -> tuple[datetime, datetime] | None:
    """Return (min_ts, max_ts) of rows with regime for a symbol. None if no data."""
    con = get_connection()
    row = con.execute(
        """
        SELECT MIN(ts), MAX(ts)
        FROM silver_features
        WHERE symbol = ? AND timeframe = ? AND regime IS NOT NULL
    """,
        [symbol, timeframe],
    ).fetchone()
    con.close()
    if row is None or row[0] is None:
        return None
    return (row[0], row[1])


def get_forward_return(
    symbol: str, timeframe: str, from_ts: datetime, periods: int
) -> float | None:
    """Return price return over `periods` candles starting at from_ts. None if incomplete."""
    con = get_connection()
    try:
        row = con.execute(
            """
            SELECT close
            FROM bronze_ohlcv
            WHERE symbol = ? AND timeframe = ? AND ts > ?
            ORDER BY ts
            LIMIT 1
            OFFSET ?
        """,
            [symbol, timeframe, from_ts, periods - 1],
        ).fetchone()
        if row is None:
            return None

        start = con.execute(
            """
            SELECT close FROM bronze_ohlcv
            WHERE symbol = ? AND timeframe = ? AND ts = ?
        """,
            [symbol, timeframe, from_ts],
        ).fetchone()
        if start is None:
            return None

        return (row[0] - start[0]) / start[0]
    finally:
        con.close()
