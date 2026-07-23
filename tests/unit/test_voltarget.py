"""Unit tests — vol-targeting shadow (capa de riesgo H10.3, decisión producto).

La variante NUNCA ejecuta ni cambia dirección: solo escala size_usd por m_t.
Offline, $0, determinista.
"""

import math

import pytest

from src.brain.voltarget import (
    LAMBDA,
    MODEL_NAME,
    PPY,
    SIGMA_TARGET,
    WARMUP,
    current_exposure,
    exposure_from_returns,
    voltarget_shadow,
)

pytestmark = pytest.mark.unit


# ── exposure_from_returns: la matemática EWMA (réplica de research/h10) ────────


def test_warmup_returns_full_exposure():
    assert exposure_from_returns([0.01] * (WARMUP - 1))["m"] == 1.0
    assert exposure_from_returns([])["m"] == 1.0


def test_low_vol_capped_at_one():
    # vol diaria 0.1% → σ_ann ≈ 1.9% ≪ 25%: m se capea en 1 (jamás apalanca)
    rets = [0.001 if i % 2 else -0.001 for i in range(40)]
    exp = exposure_from_returns(rets)
    assert exp["m"] == 1.0
    assert exp["sigma_ann"] < SIGMA_TARGET


def test_high_vol_descales():
    # vol diaria 5% → σ_ann ≈ 95%: m ≈ 25/95 ≈ 0.26
    rets = [0.05 if i % 2 else -0.05 for i in range(40)]
    exp = exposure_from_returns(rets)
    assert exp["m"] < 0.5
    assert exp["m"] == pytest.approx(SIGMA_TARGET / exp["sigma_ann"], abs=1e-3)


def test_ewma_matches_hand_rolled():
    rets = [0.01, -0.02, 0.03, -0.01, 0.02] * 5  # n=25 > warmup
    mean = sum(rets[:WARMUP]) / WARMUP
    v = sum((r - mean) ** 2 for r in rets[:WARMUP]) / WARMUP
    for r in rets[WARMUP - 1 :]:
        v = LAMBDA * v + (1 - LAMBDA) * r * r
    expected = min(1.0, SIGMA_TARGET / math.sqrt(v * PPY))
    assert exposure_from_returns(rets)["m"] == pytest.approx(expected, abs=1e-4)


# ── current_exposure: desde la curva oficial (último punto por día) ────────────


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "vt.duckdb"))
    return tmp_path


def _seed_equity_curve(equities):
    from src.data.db import get_connection

    con = get_connection()
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS equity_curve "
            "(ts TIMESTAMP NOT NULL, balance DOUBLE, equity DOUBLE)"
        )
        for i, eq in enumerate(equities):
            con.execute(
                "INSERT INTO equity_curve VALUES (TIMESTAMP '2026-01-01' + INTERVAL (?) DAY, ?, ?)",
                [i, eq, eq],
            )
    finally:
        con.close()


def test_no_equity_curve_full_exposure(tmp_db):
    exp = current_exposure()
    assert exp["m"] == 1.0
    assert exp["n_rets"] == 0


def test_short_history_full_exposure(tmp_db):
    _seed_equity_curve([100.0, 101.0, 99.0])  # 2 retornos < warmup
    assert current_exposure()["m"] == 1.0


def test_volatile_curve_descales(tmp_db):
    eq, x = [], 100.0
    for i in range(40):
        x *= 1.06 if i % 2 else 0.94  # ±6% diario → σ_ann enorme
        eq.append(x)
    exp = current_exposure()  # aún sin datos → 1.0
    _seed_equity_curve(eq)
    exp = current_exposure()
    assert exp["m"] < 0.5
    assert exp["n_rets"] == 39


# ── voltarget_shadow: filas para shadow_signals ────────────────────────────────


def test_shadow_rows_scale_size_not_direction(tmp_db, monkeypatch):
    import src.brain.voltarget as vt

    monkeypatch.setattr(
        vt, "current_exposure", lambda: {"m": 0.4, "sigma_ann": 0.625, "n_rets": 30}
    )
    champion = [
        {"symbol": "BTC/USDT", "direction": "BUY", "confidence": 0.9, "size_usd": 100.0},
        {"symbol": "ETH/USDT", "direction": "HOLD", "confidence": 0.0, "size_usd": 0.0},
    ]
    rows = vt.voltarget_shadow(champion)
    assert [r["model"] for r in rows] == [MODEL_NAME] * 2
    assert rows[0]["direction"] == "BUY"  # dirección INTACTA
    assert rows[0]["size_usd"] == pytest.approx(40.0)  # 100 × 0.4
    assert rows[0]["raw_probability"] == 0.4  # m_t documentado en el campo
    assert rows[1]["size_usd"] == 0.0


def test_empty_signals_no_rows(tmp_db):
    assert voltarget_shadow([]) == []


def test_quant_node_emits_voltarget_shadow(tmp_db, monkeypatch):
    # El nodo quant agrega la variante al stream shadow sin tocar quant_signals.
    from src.brain.agents.quant import quant_core_node

    state = {
        "symbols": ["BTC/USDT"],
        "gold_signals": [
            {
                "symbol": "BTC/USDT",
                "regime": "trending",
                "features": {"garch_vol": 0.01, "hurst": 0.6, "returns_24h": 0.02},
            }
        ],
    }
    out = quant_core_node(state)
    models = {s["model"] for s in out["shadow_signals"]}
    assert MODEL_NAME in models  # variante presente
    assert len([s for s in out["shadow_signals"] if s["model"] == MODEL_NAME]) == len(
        out["quant_signals"]
    )
