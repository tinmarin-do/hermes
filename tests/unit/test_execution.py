"""Unit tests for the execution layer (PaperAdapter + kill switch).

All tests run against an isolated temp DuckDB and temp kill-switch file —
no network, no real exchange. BinanceAdapter (ccxt) is not exercised here.
"""
from datetime import datetime, timezone

import pytest

from src.data.db import get_connection
from src.execution.kill import kill_switch


def _seed_price(symbol: str, price: float) -> None:
    """Insert one bronze_ohlcv row so PaperAdapter has a fill price."""
    con = get_connection()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        con.execute(
            """INSERT INTO bronze_ohlcv
               (symbol, timeframe, ts, open, high, low, close, volume, ingested_at)
               VALUES (?, '1h', ?, ?, ?, ?, ?, ?, ?)""",
            [symbol, now, price, price, price, price, 1.0, now],
        )
    finally:
        con.close()


@pytest.fixture
def paper(tmp_path, monkeypatch):
    """Isolated PaperAdapter: temp DuckDB + temp kill switch, switch reset to alive."""
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setattr(kill_switch, "_path", tmp_path / "kill.json")
    kill_switch.deactivate()  # ensure alive (active=False)

    from src.execution.adapter import PaperAdapter
    return PaperAdapter(initial_balance=500.0)


def test_hold_returns_cancelled(paper):
    res = paper.execute({"action": "HOLD", "symbol": "NONE", "size_usd": 0}, "run-1")
    assert res.status == "CANCELLED"
    assert res.quantity == 0


def test_zero_size_returns_cancelled(paper):
    res = paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 0}, "run-1")
    assert res.status == "CANCELLED"


def test_no_price_data_rejected(paper):
    # No _seed_price call → no row in bronze_ohlcv for this symbol.
    res = paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    assert res.status == "REJECTED"
    assert "No price" in res.error


def test_insufficient_balance_rejected(paper):
    _seed_price("BTC/USDT", 100.0)
    res = paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 1000}, "run-1")
    assert res.status == "REJECTED"
    assert "Insufficient balance" in res.error


def test_successful_fill_creates_position(paper):
    _seed_price("BTC/USDT", 100.0)
    res = paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")

    assert res.status == "FILLED"
    assert res.price == 100.0
    assert res.quantity == pytest.approx(0.5)
    assert res.fee_usd == pytest.approx(0.05)  # 0.1% of 50

    positions = paper.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTC/USDT"
    assert positions[0].action == "BUY"
    assert positions[0].quantity == pytest.approx(0.5)


def test_balance_decreases_after_fill(paper):
    _seed_price("BTC/USDT", 100.0)
    assert paper.get_balance() == 500.0
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    # cost = 50 + 0.05 fee
    assert paper.get_balance() == pytest.approx(449.95)


def test_long_position_pnl(paper):
    _seed_price("BTC/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    # price moves up to 120 → long unrealized = (120-100)*0.5 = 10
    _seed_price("BTC/USDT", 120.0)
    positions = paper.get_positions()
    assert positions[0].unrealized_pnl == pytest.approx(10.0)


def test_short_position_pnl(paper):
    _seed_price("ETH/USDT", 100.0)
    paper.execute({"action": "SELL", "symbol": "ETH/USDT", "size_usd": 50}, "run-1")
    # price moves up to 120 → short unrealized = (100-120)*0.5 = -10
    _seed_price("ETH/USDT", 120.0)
    positions = paper.get_positions()
    short = next(p for p in positions if p.symbol == "ETH/USDT")
    assert short.unrealized_pnl == pytest.approx(-10.0)


def test_kill_switch_halts_trading(paper):
    _seed_price("BTC/USDT", 100.0)
    kill_switch.activate("test halt")
    assert paper.is_alive() is False

    res = paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    assert res.status == "REJECTED"
    assert "Kill switch" in res.error


def test_kill_closes_all_positions(paper):
    _seed_price("BTC/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    assert len(paper.get_positions()) == 1

    paper.kill()
    assert paper.is_alive() is False
    assert len(paper.get_positions()) == 0  # all closed
