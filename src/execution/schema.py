"""Shared DuckDB schema for the execution layer.

Both PaperAdapter and BinanceAdapter persist orders into `execution_orders`,
so the DDL lives here and is called from each adapter's constructor. This
prevents BinanceAdapter (testnet/live) from crashing on persist when no
PaperAdapter was ever instantiated to create the table.
"""
from __future__ import annotations

from src.data.db import get_connection


def ensure_execution_schema() -> None:
    """Create execution tables if they don't exist. Idempotent."""
    con = get_connection()
    try:
        con.execute("""
            CREATE TABLE IF NOT EXISTS execution_orders (
                order_id   VARCHAR PRIMARY KEY,
                run_id     VARCHAR NOT NULL,
                symbol     VARCHAR NOT NULL,
                action     VARCHAR NOT NULL,
                quantity   DOUBLE NOT NULL,
                price      DOUBLE,
                status     VARCHAR NOT NULL DEFAULT 'PENDING',
                filled_at  TIMESTAMP,
                created_at TIMESTAMP NOT NULL,
                error      VARCHAR,
                cost_usd   DOUBLE DEFAULT 0,
                fee_usd    DOUBLE DEFAULT 0
            )
        """)
        con.execute("""
            CREATE SEQUENCE IF NOT EXISTS seq_positions_id START 1
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS execution_positions (
                id            INTEGER PRIMARY KEY DEFAULT nextval('seq_positions_id'),
                symbol        VARCHAR NOT NULL,
                action        VARCHAR NOT NULL,
                quantity      DOUBLE NOT NULL,
                entry_price   DOUBLE NOT NULL,
                opened_at     TIMESTAMP NOT NULL,
                closed_at     TIMESTAMP,
                exit_price    DOUBLE,
                realized_pnl  DOUBLE DEFAULT 0,
                run_id        VARCHAR NOT NULL,
                status        VARCHAR NOT NULL DEFAULT 'OPEN'
            )
        """)
    finally:
        con.close()
