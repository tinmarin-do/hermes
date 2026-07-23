"""Tests del ejecutor F7 — firma HMAC, redondeos, plan de órdenes y guardrails."""

import hashlib
import hmac
from typing import Any

import numpy as np
import pytest

from src.execution.binance_futures import BinanceFuturesClient, round_step
from src.execution.spread_executor import (
    build_target_weights,
    latest_standing_book_entry,
    plan_orders,
    to_perp,
)

pytestmark = pytest.mark.unit

FILTERS = {
    "AUSDT": {"min_notional": 5.0, "step_size": 0.01},
    "BUSDT": {"min_notional": 5.0, "step_size": 0.1},
}
MARKS = {"AUSDT": 100.0, "BUSDT": 2.0}


def test_firma_hmac_correcta() -> None:
    captured: dict[str, str] = {}

    def transport(method: str, url: str, headers: dict[str, str]) -> tuple[int, Any]:
        captured["url"], captured["key"] = url, headers.get("X-MBX-APIKEY", "")
        return 200, []

    c = BinanceFuturesClient("mykey", "mysecret", transport=transport)
    c._signed("GET", "/fapi/v2/balance")
    qs, sig = captured["url"].split("?", 1)[1].rsplit("&signature=", 1)
    expected = hmac.new(b"mysecret", qs.encode(), hashlib.sha256).hexdigest()
    assert sig == expected and captured["key"] == "mykey"
    assert "timestamp=" in qs and "recvWindow=" in qs


def test_round_step_hacia_abajo() -> None:
    assert round_step(0.1234, 0.01) == pytest.approx(0.12)
    assert round_step(7.999, 1.0) == pytest.approx(7.0)
    assert round_step(0.05, 0.1) == 0.0


def test_plan_libro_simple_dos_patas() -> None:
    # pesos realistas de pata (~10% c/u, como el libro 5+5 real; bajo el cap 15%)
    target = {"A": 0.10, "B": -0.10}
    plan = plan_orders(target, 1000.0, MARKS, {}, FILTERS)
    assert "orders" in plan
    by_sym = {o["symbol"]: o for o in plan["orders"]}
    assert by_sym["AUSDT"]["side"] == "BUY" and by_sym["AUSDT"]["qty"] == pytest.approx(1.0)
    assert by_sym["BUSDT"]["side"] == "SELL" and by_sym["BUSDT"]["qty"] == pytest.approx(50.0)


def test_plan_cash_si_balance_no_alcanza_min_notional() -> None:
    target = {"A": 0.04, "B": -0.04}  # 4 USDT por pata con balance 100 → bajo el mínimo 5
    plan = plan_orders(target, 100.0, MARKS, {}, FILTERS)
    assert "cash" in plan and "MIN_NOTIONAL" in plan["cash"]


def test_plan_cash_si_falta_perp() -> None:
    plan = plan_orders({"ZZZ": 0.5}, 100.0, MARKS, {}, FILTERS)
    assert "cash" in plan and "sin contrato" in plan["cash"]


def test_plan_cash_si_excede_cap_por_simbolo() -> None:
    plan = plan_orders({"A": 0.5, "B": -0.16}, 100.0, MARKS, {}, FILTERS)
    assert "cash" in plan and "cap" in plan["cash"]


def test_plan_cierra_flip_con_reduce_only_y_reabre() -> None:
    target = {"A": 0.1}  # objetivo: largo 10 USDT → 0.1 unidades
    positions = {"AUSDT": -0.30}  # hoy corto → flip
    plan = plan_orders(target, 100.0, MARKS, positions, FILTERS)
    closes = [o for o in plan["orders"] if o["reduce_only"]]
    opens = [o for o in plan["orders"] if not o["reduce_only"]]
    assert closes[0]["symbol"] == "AUSDT" and closes[0]["side"] == "BUY"
    assert closes[0]["qty"] == pytest.approx(0.30)
    assert opens[0]["side"] == "BUY" and opens[0]["qty"] == pytest.approx(0.1)


def test_plan_cierra_posicion_fuera_del_libro() -> None:
    plan = plan_orders({"A": 0.1}, 100.0, MARKS, {"BUSDT": 10.0}, FILTERS)
    close = next(o for o in plan["orders"] if o["symbol"] == "BUSDT")
    assert close["side"] == "SELL" and close["reduce_only"] is True


def test_standing_book_toma_ultimo_rebalanceo() -> None:
    entries = [
        {"decision_date": "2026-07-11", "is_rebalance": True, "universe": [{"symbol": "BTC"}]},
        {"decision_date": "2026-07-12", "is_rebalance": False, "universe": [{"symbol": "BTC"}]},
        {"decision_date": "2026-08-08", "is_rebalance": True, "universe": [{"symbol": "BTC"}]},
        {"decision_date": "2026-08-09", "is_rebalance": False, "universe": [{"symbol": "BTC"}]},
    ]
    st = latest_standing_book_entry(entries)
    assert st is not None and st["decision_date"] == "2026-08-08"


def test_build_target_weights_neutral() -> None:
    entry = {
        "universe": [
            {"symbol": f"S{i}", "p": p}
            for i, p in enumerate([0.9, 0.8, 0.7, 0.6, 0.55, 0.45, 0.4, 0.3, 0.2, 0.1])
        ]
    }
    sigma = {f"S{i}": 0.02 for i in range(10)}
    w = build_target_weights(entry, sigma, 5, "ivol")
    assert np.isclose(sum(w.values()), 0.0)
    assert np.isclose(sum(abs(v) for v in w.values()), 1.0)
    assert w["S0"] > 0 > w["S9"]


def test_to_perp() -> None:
    assert to_perp("BTC") == "BTCUSDT"


def test_plumbing_universe_filtra_y_adapta_k() -> None:
    from src.execution.spread_executor import plumbing_universe

    entry = {
        "universe": [
            {"symbol": "BTC", "p": 0.9},
            {"symbol": "ETH", "p": 0.8},
            {"symbol": "A", "p": 0.7},
            {"symbol": "B", "p": 0.6},
            {"symbol": "C", "p": 0.4},
            {"symbol": "D", "p": 0.3},
            {"symbol": "E", "p": 0.2},
            {"symbol": "F", "p": 0.1},
        ]
    }
    filters = {
        "BTCUSDT": {"min_notional": 50.0, "step_size": 0.001},
        "ETHUSDT": {"min_notional": 20.0, "step_size": 0.001},
        **{f"{s}USDT": {"min_notional": 5.0, "step_size": 0.1} for s in "ABCDEF"},
    }
    marks = {"BTCUSDT": 62000.0, "ETHUSDT": 1800.0, **{f"{s}USDT": 10.0 for s in "ABCDEF"}}
    # balance 100: k=3 → pata real 15 → BTC (62) y ETH (20) fuera; 6 ≥ 6 → k=3
    filtered, k = plumbing_universe(entry, 100.0, marks, filters)
    assert k == 3
    assert [u["symbol"] for u in filtered["universe"]] == list("ABCDEF")
    # balance 141 (el caso del bug real): k=4 daría pata 15.9 < ETH 20 con solo
    # 6 asequibles (<8) → cae a k=3 (pata 21.2, ETH cabe, 8 ≥ 6) y TODOS los
    # del universo filtrado soportan la pata real de k=3
    filtered2, k2 = plumbing_universe(entry, 141.0, marks, filters)
    assert k2 == 3
    assert "ETH" in [u["symbol"] for u in filtered2["universe"]]
    assert "BTC" not in [u["symbol"] for u in filtered2["universe"]]
    # balance 700: pata k=4 = 78.75 → los 8 caben (BTC 62 ✓) → k=4
    _, k3 = plumbing_universe(entry, 700.0, marks, filters)
    assert k3 == 4
    # balance 30: nadie soporta ni k=3 (pata 4.5 < min 5) → k=0 → CASH
    _, k4 = plumbing_universe(entry, 30.0, marks, filters)
    assert k4 == 0
