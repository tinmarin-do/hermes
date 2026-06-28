"""Integration tests for BinanceAdapter against Binance **testnet** (ccxt).

These hit the real testnet API, so they auto-skip unless BINANCE_TESTNET_API_KEY
and BINANCE_TESTNET_API_SECRET are set — same pattern as the e2e suite skipping
without DEEPSEEK_API_KEY. They never run in CI (CI is `-m unit`).

Safety:
- Default run is READ-ONLY: connectivity, balance, ticker, and the adapter guards
  (kill switch / HOLD) that short-circuit BEFORE any network order.
- The one test that places a REAL order on testnet is gated behind an extra opt-in
  env var HERMES_TESTNET_ALLOW_ORDERS=1, because sending an order to an exchange is
  outward-facing even on testnet. Without it, that test skips.

Run with:  uv run pytest tests/integration/ -m integration -v
"""

import os

import pytest

from src.execution.kill import kill_switch

_HAS_CREDS = bool(
    os.environ.get("BINANCE_TESTNET_API_KEY") and os.environ.get("BINANCE_TESTNET_API_SECRET")
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _HAS_CREDS, reason="BINANCE_TESTNET_API_KEY/SECRET not set"),
]

SYMBOL = "BTC/USDT"


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    """Isolated BinanceAdapter(testnet): temp DuckDB for order persistence + temp
    kill switch reset to alive, so tests never touch the real DB or kill file."""
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "test.duckdb"))
    monkeypatch.setattr(kill_switch, "_path", tmp_path / "kill.json")
    kill_switch.deactivate()

    from src.execution.binance import BinanceAdapter

    return BinanceAdapter(mode="testnet")


# ── Configuration (no network) ──────────────────────────────────────────────


def test_testnet_sandbox_mode_configured(adapter):
    assert adapter.mode == "testnet"
    # set_sandbox_mode(True) rewires the api url to the test endpoint.
    assert "test" in str(adapter._exchange.urls["api"]).lower()


# ── Read-only connectivity (network, no orders) ─────────────────────────────


def test_fetch_balance_returns_float(adapter):
    bal = adapter.get_balance()
    assert isinstance(bal, float)
    assert bal >= 0.0


def test_fetch_ticker_has_positive_price(adapter):
    ticker = adapter._exchange.fetch_ticker(SYMBOL)
    price = ticker.get("last") or ticker.get("close")
    assert price is not None
    assert float(price) > 0


def test_get_positions_returns_list(adapter):
    # Spot has no futures positions; the adapter swallows the error → []. Either
    # way the contract is a list.
    assert isinstance(adapter.get_positions(), list)


# ── Guards short-circuit BEFORE any exchange call ───────────────────────────


def test_hold_decision_places_no_order(adapter):
    res = adapter.execute({"action": "HOLD", "symbol": "NONE", "size_usd": 0}, "it-run")
    assert res.status == "CANCELLED"
    assert res.quantity == 0


def test_zero_size_places_no_order(adapter):
    res = adapter.execute({"action": "BUY", "symbol": SYMBOL, "size_usd": 0}, "it-run")
    assert res.status == "CANCELLED"


def test_kill_switch_blocks_order(adapter):
    kill_switch.activate("integration test halt")
    assert adapter.is_alive() is False
    res = adapter.execute({"action": "BUY", "symbol": SYMBOL, "size_usd": 50}, "it-run")
    assert res.status == "REJECTED"
    assert "Kill switch" in res.error


# ── Real order round-trip (opt-in, places a live testnet order) ─────────────


@pytest.mark.skipif(
    os.environ.get("HERMES_TESTNET_ALLOW_ORDERS") != "1",
    reason="set HERMES_TESTNET_ALLOW_ORDERS=1 to place a real testnet order",
)
def test_market_buy_round_trip(adapter):
    """Place a small market BUY on testnet and assert a well-formed OrderResult.

    Accepts FILLED or a REASONED rejection (min-notional / balance) — both prove
    the ccxt round-trip works without raising. Size is overridable via
    HERMES_TESTNET_ORDER_USD (default $15, above Binance's typical min notional).
    """
    size_usd = float(os.environ.get("HERMES_TESTNET_ORDER_USD", "15"))
    res = adapter.execute({"action": "BUY", "symbol": SYMBOL, "size_usd": size_usd}, "it-run")

    assert res.status in {"FILLED", "REJECTED"}
    assert res.symbol == SYMBOL
    assert res.action == "BUY"
    if res.status == "FILLED":
        assert res.quantity > 0
        assert res.price > 0
    else:
        assert res.error  # rejection must carry a reason
