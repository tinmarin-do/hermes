"""Unit tests — cost basis desde execution_orders (fix hallazgo G). Offline, $0."""

from datetime import datetime, timedelta

import pytest

from src.execution.costbasis import cost_basis
from src.execution.schema import ensure_execution_schema

pytestmark = pytest.mark.unit

T0 = datetime(2026, 7, 1, 12, 0, 0)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "cb.duckdb"))
    ensure_execution_schema()
    return tmp_path


def _insert(symbol, action, qty, price, fee=0.0, status="FILLED", minutes=0):
    from src.data.db import get_connection

    con = get_connection()
    try:
        ts = T0 + timedelta(minutes=minutes)
        con.execute(
            "INSERT INTO execution_orders (order_id, run_id, symbol, action, quantity, "
            "price, status, filled_at, created_at, cost_usd, fee_usd) "
            "VALUES (?, 'r', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [f"o-{symbol}-{minutes}", symbol, action, qty, price, status, ts, ts, qty * price, fee],
        )
    finally:
        con.close()


def test_empty_orders_empty_basis(tmp_db):
    assert cost_basis() == {}


def test_single_buy_sets_avg_cost(tmp_db):
    _insert("SOL/USDT", "BUY", 2.0, 100.0, fee=0.72)
    b = cost_basis()["SOL/USDT"]
    assert b["qty"] == pytest.approx(2.0)
    assert b["avg_cost"] == pytest.approx(100.0)
    assert b["fees_usd"] == pytest.approx(0.72)
    assert b["realized_pnl"] == 0.0


def test_two_buys_average_cost(tmp_db):
    _insert("SOL/USDT", "BUY", 1.0, 100.0, minutes=0)
    _insert("SOL/USDT", "BUY", 1.0, 120.0, minutes=1)
    b = cost_basis()["SOL/USDT"]
    assert b["qty"] == pytest.approx(2.0)
    assert b["avg_cost"] == pytest.approx(110.0)


def test_sell_realizes_pnl_and_reduces_basis(tmp_db):
    _insert("SOL/USDT", "BUY", 2.0, 100.0, minutes=0)
    _insert("SOL/USDT", "SELL", 1.0, 130.0, minutes=1)  # +$30 realizados
    b = cost_basis()["SOL/USDT"]
    assert b["realized_pnl"] == pytest.approx(30.0)
    assert b["qty"] == pytest.approx(1.0)
    assert b["avg_cost"] == pytest.approx(100.0)  # el promedio no cambia al vender


def test_sell_beyond_tracked_qty_clamped(tmp_db):
    # Vendí 3 pero Hermes solo compró 1 (el resto era depósito externo):
    # solo se realiza P&L sobre la parte trackeada, sin inventar historia.
    _insert("SOL/USDT", "BUY", 1.0, 100.0, minutes=0)
    _insert("SOL/USDT", "SELL", 3.0, 130.0, minutes=1)
    b = cost_basis()["SOL/USDT"]
    assert b["realized_pnl"] == pytest.approx(30.0)  # (130−100)×1, no ×3
    assert b["qty"] == pytest.approx(0.0)


def test_rejected_orders_ignored(tmp_db):
    _insert("SOL/USDT", "BUY", 1.0, 100.0, status="REJECTED")
    assert cost_basis() == {}


def test_symbols_filter(tmp_db):
    _insert("SOL/USDT", "BUY", 1.0, 100.0, minutes=0)
    _insert("ETH/USDT", "BUY", 1.0, 3000.0, minutes=1)
    assert set(cost_basis(["SOL/USDT"])) == {"SOL/USDT"}


def test_chronological_order_matters(tmp_db):
    # SELL primero en el reloj pero insertado después: sin qty previa → clamp a 0.
    _insert("SOL/USDT", "BUY", 1.0, 100.0, minutes=10)
    _insert("SOL/USDT", "SELL", 1.0, 130.0, minutes=0)
    b = cost_basis()["SOL/USDT"]
    assert b["realized_pnl"] == 0.0  # el SELL ocurrió antes de tener basis
    assert b["qty"] == pytest.approx(1.0)
