import os

import duckdb

# Paths whose schema has already been ensured this process — avoids re-running
# 5 CREATE TABLE IF NOT EXISTS on every connection (hot in tight loops like
# walk-forward / aggregate, where get_connection is called thousands of times).
_ensured_paths: set[str] = set()


def get_connection() -> duckdb.DuckDBPyConnection:
    path = os.environ.get("HERMES_DUCKDB_PATH", "data/hermes.duckdb")
    con = duckdb.connect(path)
    if path not in _ensured_paths:
        _ensure_schema(con)
        _ensured_paths.add(path)
    return con


def _ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS bronze_ohlcv (
            symbol    VARCHAR   NOT NULL,
            timeframe VARCHAR   NOT NULL,
            ts        TIMESTAMP NOT NULL,
            open      DOUBLE    NOT NULL,
            high      DOUBLE    NOT NULL,
            low       DOUBLE    NOT NULL,
            close     DOUBLE    NOT NULL,
            volume    DOUBLE    NOT NULL,
            ingested_at TIMESTAMP NOT NULL,
            PRIMARY KEY (symbol, timeframe, ts)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver_features (
            symbol      VARCHAR   NOT NULL,
            timeframe   VARCHAR   NOT NULL,
            ts          TIMESTAMP NOT NULL,
            close       DOUBLE    NOT NULL,
            returns     DOUBLE,
            log_returns DOUBLE,
            hurst       DOUBLE,
            garch_vol   DOUBLE,
            spread      DOUBLE,
            regime      VARCHAR,
            regime_conf DOUBLE,
            computed_at TIMESTAMP NOT NULL,
            PRIMARY KEY (symbol, timeframe, ts)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS bronze_news (
            id            VARCHAR   NOT NULL,
            source        VARCHAR   NOT NULL,
            url           VARCHAR,
            title         VARCHAR   NOT NULL,
            body          VARCHAR,
            published_at  TIMESTAMP NOT NULL,
            symbols       VARCHAR,
            injection_flag BOOLEAN  DEFAULT FALSE,
            injection_score DOUBLE,
            ingested_at   TIMESTAMP NOT NULL,
            PRIMARY KEY (id, source)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver_news_clusters (
            id            VARCHAR   NOT NULL,
            source        VARCHAR   NOT NULL,
            published_at  TIMESTAMP NOT NULL,
            cluster_id    INTEGER   NOT NULL,
            cluster_label VARCHAR,
            is_noise      BOOLEAN   DEFAULT FALSE,
            trust_score   DOUBLE,
            computed_at   TIMESTAMP NOT NULL,
            PRIMARY KEY (id, source)
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS gold_signals (
            symbol        VARCHAR   NOT NULL,
            timeframe     VARCHAR   NOT NULL,
            ts            TIMESTAMP NOT NULL,
            regime        VARCHAR   NOT NULL,
            regime_conf   DOUBLE    NOT NULL,
            hurst         DOUBLE,
            garch_vol     DOUBLE,
            spread        DOUBLE,
            returns_1h    DOUBLE,
            returns_24h   DOUBLE,
            signal_json   VARCHAR   NOT NULL,
            computed_at   TIMESTAMP NOT NULL,
            PRIMARY KEY (symbol, timeframe, ts)
        )
    """)
