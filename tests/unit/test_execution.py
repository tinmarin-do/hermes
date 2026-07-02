"""Unit tests for the execution layer (PaperAdapter + kill switch).

All tests run against an isolated temp DuckDB and temp kill-switch file —
no network, no real exchange. BinanceAdapter (ccxt) is not exercised here.
"""

from datetime import UTC, datetime

import pytest

from src.data.db import get_connection
from src.execution.kill import kill_switch

pytestmark = pytest.mark.unit


def _seed_price(symbol: str, price: float) -> None:
    """Insert one bronze_ohlcv row so PaperAdapter has a fill price."""
    con = get_connection()
    now = datetime.now(UTC).replace(tzinfo=None)
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


# ── Neteo (§8.8 Fase 2): reciclaje de caja + posición neta por símbolo ─────────


def test_sell_reduces_long_and_recycles_cash(paper):
    _seed_price("BTC/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    _seed_price("BTC/USDT", 120.0)
    res = paper.execute({"action": "SELL", "symbol": "BTC/USDT", "size_usd": 20}, "run-2")

    assert res.status == "FILLED"
    positions = paper.get_positions()
    assert len(positions) == 1  # sigue UNA posición neta, reducida
    p = positions[0]
    assert p.action == "BUY"
    assert p.quantity == pytest.approx(0.5 - 20 / 120, abs=1e-6)
    # realized de la porción vendida: (120-100) × 0.166667 ≈ +3.33
    assert p.realized_pnl == pytest.approx(3.3333, abs=0.01)
    # caja: 500 − 50.05 (buy) + 19.98 (sell 20 − fee 0.02) = 469.93
    assert paper.get_balance() == pytest.approx(469.93, abs=0.01)


def test_sell_beyond_long_flips_to_short(paper):
    _seed_price("ETH/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "ETH/USDT", "size_usd": 50}, "run-1")
    paper.execute({"action": "SELL", "symbol": "ETH/USDT", "size_usd": 60}, "run-2")

    positions = paper.get_positions()
    assert len(positions) == 1  # el largo cerró; queda solo el short remanente
    p = positions[0]
    assert p.action == "SELL"
    assert p.quantity == pytest.approx(0.1, abs=1e-6)  # 0.6 vendido − 0.5 cerrado


def test_buy_covers_short_with_realized_pnl(paper):
    _seed_price("BTC/USDT", 100.0)
    paper.execute({"action": "SELL", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    _seed_price("BTC/USDT", 80.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 30}, "run-2")

    positions = paper.get_positions()
    assert len(positions) == 1
    p = positions[0]
    assert p.action == "SELL"
    assert p.quantity == pytest.approx(0.5 - 30 / 80, abs=1e-6)  # 0.125 sigue corto
    # short cubierto ganando: (100-80) × 0.375 = +7.5
    assert p.realized_pnl == pytest.approx(7.5, abs=0.01)


def test_buy_merges_with_weighted_average_entry(paper):
    _seed_price("BTC/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    _seed_price("BTC/USDT", 200.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-2")

    positions = paper.get_positions()
    assert len(positions) == 1  # UNA fila neta, no dos
    p = positions[0]
    assert p.quantity == pytest.approx(0.75, abs=1e-6)  # 0.5 + 0.25
    assert p.entry_price == pytest.approx(133.3333, abs=0.01)  # promedio ponderado


def test_full_close_books_realized_and_frees_book(paper):
    _seed_price("ETH/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "ETH/USDT", "size_usd": 50}, "run-1")
    _seed_price("ETH/USDT", 110.0)
    paper.execute({"action": "SELL", "symbol": "ETH/USDT", "size_usd": 55}, "run-2")

    assert paper.get_positions() == []  # libro limpio (0.5 × 110 = 55 exacto)
    # equity final = caja sola: 500 − 50.05 + 54.945 = 504.895 (pnl +5 − fees 0.105)
    assert paper.get_equity() == pytest.approx(504.895, abs=0.01)


def test_equity_tracks_cash_plus_book(paper):
    _seed_price("BTC/USDT", 100.0)
    paper.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "run-1")
    assert paper.get_equity() == pytest.approx(499.95, abs=0.01)  # solo la fee
    _seed_price("BTC/USDT", 120.0)
    assert paper.get_equity() == pytest.approx(509.95, abs=0.01)  # + pnl 10


# ── Test de aceptación Fase 2: ciclo de rebalanceo día 0 → día 1 converge ─────


def _book_dicts(adapter):
    return [
        {
            "symbol": p.symbol,
            "action": p.action,
            "quantity": p.quantity,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
        }
        for p in adapter.get_positions()
    ]


def _run_legs(adapter, legs, run_id):
    # SELLs primero (como el runner): liberan la caja de los BUYs del mismo ciclo
    for leg in sorted(
        (a for a in legs if a["action"] != "HOLD" and a["size_usd"] > 0),
        key=lambda a: 0 if a["action"] == "SELL" else 1,
    ):
        res = adapter.execute(
            {"action": leg["action"], "symbol": leg["symbol"], "size_usd": leg["size_usd"]},
            run_id,
        )
        assert res.status == "FILLED", res.error


def test_rebalance_cycle_converges(paper):
    """PRD v0.3 §9 Fase 2: dos corridas consecutivas convergen a los pesos objetivo."""
    from src.brain.agents.allocator import compute_allocations
    from src.execution.adapter import PaperAdapter

    a = PaperAdapter(initial_balance=1.0)  # era-$1 (mismo DuckDB temp del fixture)
    _seed_price("BTC/USDT", 100.0)
    _seed_price("ETH/USDT", 50.0)

    # ── Día 0: todo cash → BUYs a pesos objetivo 2/3 · 1/3 ──
    sigs_d0 = [
        {"symbol": "BTC/USDT", "direction": "BUY", "confidence": 0.9, "garch_vol": 0.01},
        {"symbol": "ETH/USDT", "direction": "BUY", "confidence": 0.45, "garch_vol": 0.01},
    ]
    legs_d0 = compute_allocations(sigs_d0, _book_dicts(a), budget=1.0, global_mult=1.0)
    _run_legs(a, legs_d0, "day-0")

    book = {p.symbol: p.quantity * (p.current_price or 0) for p in a.get_positions()}
    assert book["BTC/USDT"] == pytest.approx(2 / 3, abs=0.02)
    assert book["ETH/USDT"] == pytest.approx(1 / 3, abs=0.02)

    # ── Día 1: precios se mueven y la convicción rota → SELL recicla hacia el BUY ──
    _seed_price("BTC/USDT", 120.0)  # BTC +20% → sobre-ponderado
    _seed_price("ETH/USDT", 40.0)  # ETH −20% → sub-ponderado
    sigs_d1 = [
        {"symbol": "BTC/USDT", "direction": "BUY", "confidence": 0.3, "garch_vol": 0.01},
        {"symbol": "ETH/USDT", "direction": "BUY", "confidence": 0.6, "garch_vol": 0.01},
    ]
    legs_d1 = compute_allocations(sigs_d1, _book_dicts(a), budget=1.0, global_mult=1.0)
    actions = {leg["symbol"]: leg["action"] for leg in legs_d1}
    assert actions["BTC/USDT"] == "SELL"  # recorta el sobre-ponderado
    assert actions["ETH/USDT"] == "BUY"  # agrega al sub-ponderado
    _run_legs(a, legs_d1, "day-1")

    # ── Convergencia: un tercer cómputo no encuentra nada que mover ──
    legs_d2 = compute_allocations(sigs_d1, _book_dicts(a), budget=1.0, global_mult=1.0)
    assert all(leg["action"] == "HOLD" for leg in legs_d2)

    # Libro final en los pesos nuevos (1/3 · 2/3) y equity coherente (PnL BTC preservado)
    book = {p.symbol: p.quantity * (p.current_price or 0) for p in a.get_positions()}
    assert book["BTC/USDT"] == pytest.approx(1 / 3, abs=0.02)
    assert book["ETH/USDT"] == pytest.approx(2 / 3, abs=0.02)
    assert a.get_equity() == pytest.approx(1.0667, abs=0.02)  # $1 + 20% sobre el 1/3 de BTC
    # invariante de neteo: una sola fila OPEN por símbolo
    symbols = [p.symbol for p in a.get_positions()]
    assert len(symbols) == len(set(symbols))
    # el SELL de BTC realizó ganancia: (120−100) × qty vendida > 0
    btc = next(p for p in a.get_positions() if p.symbol == "BTC/USDT")
    assert btc.realized_pnl > 0
