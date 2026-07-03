"""Unit tests for the deterministic portfolio allocator (§8.8).

Pure functions, no network/DB: we feed plain dicts to compute_allocations and assert the
target-weight math, the conservative short cap, and the delta-vs-book rebalancing logic.
"""

import pytest

from src.brain.agents.allocator import compute_allocations
from src.brain.quant_core import _prob_to_signal

pytestmark = pytest.mark.unit


def _sig(symbol, direction, confidence, garch_vol):
    return {
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "garch_vol": garch_vol,
    }


# ── Día 0: libro vacío, dos longs ────────────────────────────────────────────


def test_day0_all_cash_deploys_buys():
    sigs = [
        _sig("BTC/USDT", "BUY", 0.6, 0.004),
        _sig("ETH/USDT", "BUY", 0.4, 0.004),
    ]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=1.0)
    by = {a["symbol"]: a for a in legs}

    assert by["BTC/USDT"]["action"] == "BUY"
    assert by["ETH/USDT"]["action"] == "BUY"
    # mismo vol → pesos proporcionales a la confianza (0.6 vs 0.4)
    assert by["BTC/USDT"]["target_weight"] == pytest.approx(0.6, abs=1e-3)
    assert by["ETH/USDT"]["target_weight"] == pytest.approx(0.4, abs=1e-3)
    # con global_mult=1 y solo longs, los targets suman el budget
    assert sum(a["target_usd"] for a in legs) == pytest.approx(1.0, abs=1e-3)


def test_inverse_vol_penalizes_volatility():
    # misma confianza, distinta vol → el más volátil pesa menos
    sigs = [
        _sig("BTC/USDT", "BUY", 0.5, 0.002),  # baja vol
        _sig("SOL/USDT", "BUY", 0.5, 0.008),  # alta vol
    ]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=1.0)
    by = {a["symbol"]: a for a in legs}
    assert by["BTC/USDT"]["target_weight"] > by["SOL/USDT"]["target_weight"]


# ── Cap de short ──────────────────────────────────────────────────────────────


def test_short_capped_at_10pct():
    # un long fuerte + un short fuerte; el short debe quedar ≤ 10% del budget
    sigs = [
        _sig("BTC/USDT", "BUY", 0.6, 0.004),
        _sig("ETH/USDT", "SELL", 0.9, 0.004),  # short de alta convicción
    ]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=1.0, short_cap_pct=0.10)
    by = {a["symbol"]: a for a in legs}
    # short = peso negativo, |peso| ≤ 0.10
    assert by["ETH/USDT"]["target_weight"] < 0
    assert abs(by["ETH/USDT"]["target_weight"]) <= 0.10 + 1e-9
    assert by["ETH/USDT"]["action"] == "SELL"


def test_no_short_when_none_signaled():
    sigs = [_sig("BTC/USDT", "BUY", 0.6, 0.004)]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=1.0)
    assert all(a["target_weight"] >= 0 for a in legs)


# ── Freno global ──────────────────────────────────────────────────────────────


def test_global_mult_zero_deploys_nothing():
    sigs = [_sig("BTC/USDT", "BUY", 0.6, 0.004)]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=0.0)
    # libro vacío + nada desplegable → todo HOLD
    assert all(a["action"] == "HOLD" for a in legs)
    assert all(a["target_usd"] == 0.0 for a in legs)


def test_global_mult_scales_deployment():
    sigs = [_sig("BTC/USDT", "BUY", 0.6, 0.004)]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=0.5)
    assert sum(a["target_usd"] for a in legs) == pytest.approx(0.5, abs=1e-3)


# ── Rebalanceo por delta vs libro ─────────────────────────────────────────────


def test_hold_signal_exits_existing_long():
    # tenemos un long de ~$0.50 en BTC pero ya no hay señal → target 0 → SELL para salir
    book = [{"symbol": "BTC/USDT", "action": "BUY", "quantity": 0.5, "current_price": 1.0}]
    legs = compute_allocations([], book, budget=1.0, global_mult=1.0)
    by = {a["symbol"]: a for a in legs}
    assert by["BTC/USDT"]["action"] == "SELL"
    assert by["BTC/USDT"]["size_usd"] == pytest.approx(0.5, abs=1e-3)


def test_delta_below_min_trade_is_hold():
    # target ≈ libro actual → delta despreciable → HOLD (no churn)
    book = [{"symbol": "BTC/USDT", "action": "BUY", "quantity": 1.0, "current_price": 1.0}]
    sigs = [_sig("BTC/USDT", "BUY", 0.5, 0.004)]
    legs = compute_allocations(sigs, book, budget=1.0, global_mult=1.0, min_trade_frac=0.05)
    assert legs[0]["action"] == "HOLD"


# ── Freno = CONGELAR, no liquidar (decisión 2026-07-03) ──────────────────────


def test_freeze_keeps_book_untouched():
    # verdict HOLD con posiciones abiertas → 0 órdenes; el libro queda como está
    # (la semántica vieja liquidaba todo: target $0 → SELL del libro entero)
    book = [{"symbol": "SOL/USDT", "action": "BUY", "quantity": 0.8, "current_price": 1.0}]
    sigs = [_sig("SOL/USDT", "SELL", 0.9, 0.004)]  # ni una señal contraria mueve el libro
    legs = compute_allocations(sigs, book, budget=1.0, global_mult=0.0, freeze=True)
    by = {a["symbol"]: a for a in legs}
    assert by["SOL/USDT"]["action"] == "HOLD"
    assert by["SOL/USDT"]["size_usd"] == 0.0
    assert by["SOL/USDT"]["target_usd"] == pytest.approx(0.8, abs=1e-3)


def test_freeze_empty_book_no_legs():
    sigs = [_sig("BTC/USDT", "BUY", 0.9, 0.004)]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=0.0, freeze=True)
    assert legs == []  # nada que congelar, nada que desplegar


def test_freeze_short_position_also_held():
    book = [{"symbol": "ETH/USDT", "action": "SELL", "quantity": 0.1, "current_price": 1.0}]
    legs = compute_allocations([], book, budget=1.0, global_mult=0.0, freeze=True)
    assert legs[0]["action"] == "HOLD"
    assert legs[0]["current_usd"] == pytest.approx(-0.1, abs=1e-3)


# ── Reserva de fees (escala $400: el último BUY no debe rebotar) ─────────────


def test_fee_reserve_shrinks_deployable():
    sigs = [_sig("BTC/USDT", "BUY", 0.6, 0.004)]
    legs = compute_allocations(sigs, [], budget=400.0, global_mult=1.0, fee_reserve_pct=0.005)
    # target = 400 × (1 − 0.005) = 398 → quedan $2 de headroom para fees
    assert sum(a["target_usd"] for a in legs) == pytest.approx(398.0, abs=0.01)


def test_fee_reserve_zero_is_backward_compatible():
    sigs = [_sig("BTC/USDT", "BUY", 0.6, 0.004)]
    legs = compute_allocations(sigs, [], budget=1.0, global_mult=1.0, fee_reserve_pct=0.0)
    assert sum(a["target_usd"] for a in legs) == pytest.approx(1.0, abs=1e-3)


# ── Umbral asimétrico de short (§8.8) ─────────────────────────────────────────


def test_asymmetric_short_threshold():
    # P=0.30 NO dispara short (umbral simétrico viejo lo hubiera hecho); P=0.25 sí.
    assert _prob_to_signal(0.30)[0] == "HOLD"
    assert _prob_to_signal(0.25)[0] == "SELL"
    assert _prob_to_signal(0.70)[0] == "BUY"
    # P=0.25 ⟺ confianza exactamente 0.50
    assert _prob_to_signal(0.25)[1] == pytest.approx(0.50, abs=1e-6)
