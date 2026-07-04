"""Unit tests — BitsoAdapter (F6): mapping de pares, long-only, caps de balance,
maker-first con fallback. Exchange FAKE inyectado — sin red, sin keys, $0."""

from typing import Any

import pytest

from src.execution.bitso import PAIR_MAP, BitsoAdapter, _venue_pair

pytestmark = pytest.mark.unit


class FakeExchange:
    """Stub mínimo de ccxt.bitso: libro estático, fills programables."""

    def __init__(
        self,
        balances: dict[str, float] | None = None,
        maker_fills: bool = True,
        price: float = 100.0,
        async_market_fill: bool = False,
        insufficient_once: bool = False,
        balance_script: list[dict[str, float]] | None = None,
        post_insufficient_balances: list[dict[str, float]] | None = None,
    ):
        self.price = price
        self.maker_fills = maker_fills
        self.async_market_fill = async_market_fill
        self.insufficient_once = insufficient_once
        self.balances = balances or {"USDT": 1000.0, "USD": 500.0}
        # Guiones de balance: cada fetch_balance consume una entrada (simula la
        # reserva de la limit liberándose lentamente); agotado → self.balances.
        self.balance_script = list(balance_script or [])
        self.post_insufficient_balances = post_insufficient_balances
        self.balance_calls = 0
        self.orders: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self._next_id = 0
        self.markets = {
            p: {
                "maker": 0.003,
                "taker": 0.0036,
                "limits": {"amount": {"min": 0.0001}, "cost": {"min": 5.0}},
            }
            for p in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "LINK/USD", "AVAX/USD"]
        }

    def load_markets(self):
        return self.markets

    def fetch_ticker(self, pair):
        return {"bid": self.price * 0.999, "ask": self.price * 1.001, "last": self.price}

    def fetch_balance(self):
        self.balance_calls += 1
        src = self.balance_script.pop(0) if self.balance_script else self.balances
        return {k: {"free": v, "total": v} for k, v in src.items()}

    def amount_to_precision(self, pair, amount):
        return f"{amount:.8f}"

    def price_to_precision(self, pair, price):
        return f"{price:.2f}"

    def create_order(self, pair, type_, side, amount, price=None):
        if type_ == "market" and self.insufficient_once:
            # 1er market post-cancel rebota: reserva de la limit aún sin liberar
            self.insufficient_once = False
            if self.post_insufficient_balances is not None:
                self.balance_script = list(self.post_insufficient_balances)
            import ccxt

            raise ccxt.InsufficientFunds('bitso {"error":{"code":"0379"}} Insufficient')
        self._next_id += 1
        oid = f"o{self._next_id}"
        filled = amount if (type_ == "market" or self.maker_fills) else 0.0
        order = {
            "id": oid,
            "symbol": pair,
            "type": type_,
            "side": side,
            "amount": amount,
            "filled": filled,
            "average": price or self.price,
            "status": "closed" if filled else "open",
        }
        self.orders[oid] = order
        if type_ == "market" and self.async_market_fill:
            # Bitso real: el response del create llega SIN fill (asíncrono); la
            # verdad vive en fetch_order (self.orders ya la tiene completa).
            self.created.append({**order, "filled": 0.0, "average": 0.0})
            return {**order, "filled": 0.0, "average": 0.0, "status": "open"}
        self.created.append(order)
        return order

    def fetch_order(self, oid, pair):
        return self.orders[oid]

    def cancel_order(self, oid, pair):
        self.cancelled.append(oid)
        self.orders[oid]["status"] = "canceled"

    def fetch_open_orders(self, pair):
        return [o for o in self.orders.values() if o["status"] == "open"]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "bitso.duckdb"))
    return tmp_path


def _adapter(fake: FakeExchange) -> BitsoAdapter:
    a = BitsoAdapter(maker_wait_s=0.0, exchange=fake)
    a._poll_s = 0.0  # tests: sin sleeps
    return a


# ── Mapping de pares ───────────────────────────────────────────────────────────


def test_pair_map_canonical_to_venue():
    assert _venue_pair("LINK/USDT") == "LINK/USD"
    assert _venue_pair("AVAX/USDT") == "AVAX/USD"
    assert _venue_pair("BTC/USDT") == "BTC/USDT"
    assert set(PAIR_MAP) == {"LINK/USDT", "AVAX/USDT"}


def test_link_order_routes_to_usd_pocket(tmp_db):
    fake = FakeExchange(balances={"USDT": 0.0, "USD": 500.0})
    r = _adapter(fake).execute({"action": "BUY", "symbol": "LINK/USDT", "size_usd": 20}, "r1")
    assert r.status == "FILLED"
    assert fake.created[0]["symbol"] == "LINK/USD"  # ejecutó en el par del venue
    assert r.symbol == "LINK/USDT"  # pero reporta el canónico


# ── Long-only + caps de balance ────────────────────────────────────────────────


def test_buy_capped_to_quote_pocket(tmp_db):
    # bolsillo USDT con $50: un BUY de $200 se achica, no rebota
    fake = FakeExchange(balances={"USDT": 50.0, "USD": 0.0})
    r = _adapter(fake).execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 200}, "r1")
    assert r.status == "FILLED"
    assert r.quantity * r.price < 50.0  # gastó menos que el bolsillo


def test_sell_capped_to_holdings_long_only(tmp_db):
    # solo tengo 0.1 SOL: un SELL de $100 (≈1 SOL) vende 0.1 — jamás abre short
    fake = FakeExchange(balances={"USDT": 0.0, "SOL": 0.1})
    r = _adapter(fake).execute({"action": "SELL", "symbol": "SOL/USDT", "size_usd": 100}, "r1")
    assert r.status == "FILLED"
    assert r.quantity == pytest.approx(0.1)


def test_sell_without_holdings_rejected(tmp_db):
    fake = FakeExchange(balances={"USDT": 100.0})
    r = _adapter(fake).execute({"action": "SELL", "symbol": "SOL/USDT", "size_usd": 50}, "r1")
    assert r.status == "REJECTED"
    assert "mínimo" in (r.error or "")


def test_order_below_min_cost_rejected(tmp_db):
    fake = FakeExchange()
    r = _adapter(fake).execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 2}, "r1")
    assert r.status == "REJECTED"  # min_cost=$5


# ── Maker-first → fallback taker ───────────────────────────────────────────────


def test_maker_fill_no_fallback(tmp_db):
    fake = FakeExchange(maker_fills=True)
    r = _adapter(fake).execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "r1")
    assert r.status == "FILLED"
    assert len(fake.created) == 1  # solo el limit
    assert fake.created[0]["type"] == "limit"
    assert fake.cancelled == []


def test_maker_timeout_falls_back_to_market(tmp_db):
    fake = FakeExchange(maker_fills=False)
    r = _adapter(fake).execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "r1")
    assert r.status == "FILLED"
    types = [o["type"] for o in fake.created]
    assert types == ["limit", "market"]  # limit sin fill → cancel → market
    assert fake.cancelled == ["o1"]


def test_market_retries_once_on_unreleased_reserve(tmp_db):
    # Carrera cazada por 29cb1a50/c385db10: cancel de la limit → market inmediato
    # rebota 0379 porque la reserva no se liberó — el retry único debe llenar.
    fake = FakeExchange(maker_fills=False, insufficient_once=True)
    r = _adapter(fake).execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 50}, "r1")
    assert r.status == "FILLED"
    assert r.quantity > 0


def test_waits_for_slow_reserve_release_before_market(tmp_db):
    # Carrera 4da7d525 (1ra daily live autónoma): el status de la limit dice
    # "canceled" en ms pero Bitso libera la reserva DESPUÉS de >10s. El adapter
    # debe vigilar el SALDO libre (no el status) y mandar el market solo cuando
    # los fondos existan — sin necesitar el retry.
    fake = FakeExchange(
        maker_fills=False,
        balances={"USDT": 50.0, "USD": 0.0},
        # fetch #1 = cap pre-orden (todo libre); #2-3 = reserva aún congelada
        # post-cancel; #4 = liberada. Luego cae a self.balances.
        balance_script=[
            {"USDT": 50.0, "USD": 0.0},
            {"USDT": 0.0, "USD": 0.0},
            {"USDT": 0.0, "USD": 0.0},
            {"USDT": 50.0, "USD": 0.0},
        ],
    )
    a = _adapter(fake)
    a._poll_s = 0.001  # el poll necesita iterar (0 = un solo vistazo)
    r = a.execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 40}, "r1")
    assert r.status == "FILLED"
    assert [o["type"] for o in fake.created] == ["limit", "market"]  # sin retry
    assert fake.balance_calls >= 4  # esperó de verdad a la liberación


def test_release_wait_emits_latency_telemetry(tmp_db, capsys):
    # Cada espera de liberación se loguea con su duración — telemetría para
    # ajustar el techo de 60s con datos reales de producción.
    fake = FakeExchange(
        maker_fills=False,
        balances={"USDT": 50.0, "USD": 0.0},
        balance_script=[
            {"USDT": 50.0, "USD": 0.0},
            {"USDT": 0.0, "USD": 0.0},
            {"USDT": 50.0, "USD": 0.0},
        ],
    )
    a = _adapter(fake)
    a._poll_s = 0.001
    a.execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 40}, "r1")
    out = capsys.readouterr().out
    assert "[bitso] reserva USDT liberada tras" in out
    assert "techo 60s" in out


def test_retry_sizes_to_actually_available_funds(tmp_db):
    # Si tras el 0379 la liberación llega PARCIAL, el retry compra lo que el
    # saldo real permite en vez de repetir el monto teórico (y volver a rebotar).
    fake = FakeExchange(
        maker_fills=False,
        insufficient_once=True,
        balances={"USDT": 100.0, "USD": 0.0},
        post_insufficient_balances=[{"USDT": 30.0, "USD": 0.0}],
    )
    r = _adapter(fake).execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 50}, "r1")
    assert r.status == "FILLED"
    # ~$30 disponibles @ ~$100 → ~0.297 SOL; jamás los 0.498 teóricos
    assert 0.25 < r.quantity < 0.31


def test_async_market_fill_not_reported_rejected(tmp_db):
    # Bug cazado por live-validation-1 (2026-07-03): Bitso responde el create del
    # market SIN fill (asíncrono) — el adapter debe consultar la orden real antes
    # de declarar REJECTED (la orden HABÍA llenado: 0.2438 SOL @ 82.335).
    fake = FakeExchange(maker_fills=False, async_market_fill=True)
    r = _adapter(fake).execute({"action": "BUY", "symbol": "SOL/USDT", "size_usd": 20}, "r1")
    assert r.status == "FILLED"
    assert r.quantity > 0


# ── Seguridad ──────────────────────────────────────────────────────────────────


def test_hold_places_nothing(tmp_db):
    fake = FakeExchange()
    r = _adapter(fake).execute({"action": "HOLD", "symbol": "NONE", "size_usd": 0}, "r1")
    assert r.status == "CANCELLED"
    assert fake.created == []


def test_kill_cancels_open_orders_and_halts(tmp_db):
    from src.execution.kill import kill_switch

    fake = FakeExchange(maker_fills=False)
    fake.create_order("BTC/USDT", "limit", "buy", 0.001, 100.0)  # orden colgada
    a = _adapter(fake)
    a.kill()
    try:
        assert fake.cancelled == ["o1"]
        r = a.execute({"action": "BUY", "symbol": "BTC/USDT", "size_usd": 50}, "r1")
        assert r.status == "REJECTED"
        assert "Kill switch" in (r.error or "")
    finally:
        kill_switch.deactivate()


def test_balance_sums_both_pockets(tmp_db):
    fake = FakeExchange(balances={"USDT": 260.0, "USD": 140.0})
    assert _adapter(fake).get_balance() == pytest.approx(400.0)


def test_positions_from_real_holdings(tmp_db):
    fake = FakeExchange(balances={"USDT": 100.0, "SOL": 0.5, "LINK": 2.0})
    pos = _adapter(fake).get_positions()
    by = {p.symbol: p for p in pos}
    assert set(by) == {"SOL/USDT", "LINK/USDT"}  # canónicos, no pares venue
    assert by["SOL/USDT"].quantity == pytest.approx(0.5)
    assert by["SOL/USDT"].action == "BUY"  # spot = siempre long


def test_equity_sums_cash_and_holdings(tmp_db):
    # cash 100 USDT + 50 USD + 0.5 SOL @ 100 = 200 (MXN residual fuera a propósito)
    fake = FakeExchange(balances={"USDT": 100.0, "USD": 50.0, "SOL": 0.5, "MXN": 9000.0})
    assert _adapter(fake).get_equity() == pytest.approx(200.0)


# ── Budget dinámico (HERMES_BUDGET_SOURCE=wallet, decisión 2026-07-03) ─────────


def test_wallet_budget_overrides_env_in_live(tmp_db, monkeypatch):
    from src.brain import runner

    class StubAdapter:
        def get_equity(self):
            return 566.4

        def get_balance(self):
            return 500.0

        def get_positions(self):
            return []

    monkeypatch.setenv("EXCHANGE_MODE", "live")
    monkeypatch.setenv("HERMES_BUDGET_SOURCE", "wallet")
    monkeypatch.setenv("HERMES_CAPITAL_USD", "400")
    monkeypatch.setattr(runner, "_get_adapter", lambda: StubAdapter())
    monkeypatch.setattr(runner, "aggregate", lambda s, t: [{"symbol": "BTC/USDT"}])
    # cortar el run apenas pasa la resolución de budget (no invocar grafo/LLM):
    # StubAdapter.get_positions lanza Stop DESPUÉS de que el budget ya se fijó.
    import os

    class Stop(Exception):
        pass

    StubAdapter.get_positions = lambda self: (_ for _ in ()).throw(Stop())
    with pytest.raises(Stop):
        runner.run(symbols=["BTC/USDT"])
    assert os.environ["HERMES_CAPITAL_USD"] == "566.40"
