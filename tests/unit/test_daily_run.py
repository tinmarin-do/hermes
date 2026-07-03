"""Unit tests — corrida diaria (freno de budget) + Silver incremental (tail)."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "daily.duckdb"))
    return tmp_path


# ── Freno de budget (regla #6 sin gate interactivo) ───────────────────────────


def test_budget_guard_blocks_when_line_exhausted(tmp_db, monkeypatch):
    from scripts import daily_run

    monkeypatch.setattr(daily_run, "DAILY_LINE_CAP_USD", 0.05)
    daily_run._record_run("r1", 0.03, "OK")
    daily_run._record_run("r2", 0.015, "OK")
    assert daily_run._month_daily_spend() == pytest.approx(0.045)
    # 0.045 + est 0.011 > 0.05 → el main debe frenar ANTES de tocar red/LLM
    rc = daily_run.main()
    assert rc == 2


def test_budget_guard_allows_within_line(tmp_db):
    from scripts import daily_run

    daily_run._record_run("r1", 0.0105, "OK")
    assert daily_run._month_daily_spend() < daily_run.DAILY_LINE_CAP_USD


def test_blocked_runs_are_recorded(tmp_db, monkeypatch):
    import duckdb

    from scripts import daily_run

    monkeypatch.setattr(daily_run, "DAILY_LINE_CAP_USD", 0.0)
    rc = daily_run.main()
    assert rc == 2
    con = duckdb.connect(str(tmp_db / "daily.duckdb"))
    status = con.execute("SELECT status FROM daily_run_log").fetchone()[0]
    con.close()
    assert status == "BLOCKED_BUDGET"


# ── Silver incremental (transform_tail) ───────────────────────────────────────


def _seed_bronze(symbol: str, hours: int, start: datetime) -> None:
    from src.data.db import get_connection

    con = get_connection()
    rows = []
    for i in range(hours):
        ts = start + timedelta(hours=i)
        px = 100.0 + i * 0.1
        rows.append([symbol, "1h", ts, px, px + 1, px - 1, px, 10.0, start])
    con.executemany(
        "INSERT OR REPLACE INTO bronze_ohlcv VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    con.close()


@pytest.fixture
def cheap_rollers(monkeypatch):
    """Los rollers reales (Hurst/GARCH) tardan minutos — para unit se stubbean."""
    import src.data.silver.transform as t

    monkeypatch.setattr(
        t, "_rolling_hurst", lambda closes, w: pd.Series(0.55, index=closes.index)
    )
    monkeypatch.setattr(
        t, "_rolling_garch_vol", lambda lr, w: pd.Series(0.005, index=lr.index)
    )
    return t


def test_tail_falls_back_to_full_without_prior_silver(tmp_db, cheap_rollers):
    t = cheap_rollers
    start = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0) - timedelta(
        hours=700
    )
    _seed_bronze("BTC/USDT", 700, start)
    n = t.transform_tail("BTC/USDT", "1h")
    assert n == 700  # sin silver previo → transform() completo


def test_tail_upserts_only_new_rows(tmp_db, cheap_rollers):
    from src.data.db import get_connection

    t = cheap_rollers
    start = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0) - timedelta(
        hours=700
    )
    _seed_bronze("BTC/USDT", 650, start)
    t.transform("BTC/USDT", "1h")  # full inicial (650 filas)

    _seed_bronze("BTC/USDT", 700, start)  # +50 velas nuevas (idempotente en las viejas)
    n = t.transform_tail("BTC/USDT", "1h", tail_hours=24)
    assert n == 24 + 50  # overlap de 24h + las 50 nuevas

    con = get_connection()
    total, dupes = con.execute(
        "SELECT count(*), count(*) - count(DISTINCT ts) FROM silver_features "
        "WHERE symbol='BTC/USDT'"
    ).fetchone()
    con.close()
    assert total == 700  # sin huecos
    assert dupes == 0  # sin duplicados (INSERT OR REPLACE por PK)
