"""Unit tests — regla momentum multi-escala (champion) + shadow mode (PRD v0.3 Fase 1).

La lógica de voto es pura (sin I/O); el acceso a bronze se monkeypatchea. El nodo quant
se testea end-to-end en memoria: champion multimom + gate de short + vector shadow.
"""

import pytest

from src.brain.quant_core import _prob_to_signal
from src.brain.quant_rule import (
    MULTISCALE_LOOKBACKS,
    multiscale_signal,
    probability_from,
    vote_from_returns,
)

pytestmark = pytest.mark.unit


# ── vote_from_returns (pura) ──────────────────────────────────────────────────


def test_unanimous_up_is_buy_max_conf():
    direction, conf = vote_from_returns([0.10, 0.20, 0.05, 0.30])
    assert direction == "BUY"
    assert conf == 0.95  # 4/4 → 1.0, cap 0.95


def test_unanimous_down_is_sell_max_conf():
    direction, conf = vote_from_returns([-0.10, -0.20, -0.05, -0.30])
    assert direction == "SELL"
    assert conf == 0.95


def test_majority_up_is_buy_half_conf():
    direction, conf = vote_from_returns([0.10, -0.10, 0.10, 0.10])
    assert direction == "BUY"
    assert conf == 0.5  # |+2| / 4


def test_scale_disagreement_is_hold():
    assert vote_from_returns([0.10, -0.10, 0.10, -0.10]) == ("HOLD", 0.0)


def test_no_data_is_hold():
    assert vote_from_returns([None, None, None, None]) == ("HOLD", 0.0)


def test_partial_data_votes_over_valid_scales():
    direction, conf = vote_from_returns([None, None, -0.10, -0.20])
    assert direction == "SELL"
    assert conf == 0.95  # 2/2 válidas, unánimes


def test_zero_return_counts_as_valid_but_does_not_vote():
    direction, conf = vote_from_returns([0.0, 0.10, None, None])
    assert direction == "BUY"
    assert conf == 0.5  # 1 voto de 2 escalas válidas


# ── probability_from ↔ _prob_to_signal (consistencia de contrato) ─────────────


def test_probability_roundtrip_buy():
    p = probability_from("BUY", 0.95)
    direction, conf = _prob_to_signal(p)
    assert direction == "BUY"
    assert conf == pytest.approx(0.95, abs=1e-6)


def test_probability_roundtrip_sell_asymmetric_gate():
    # conf 0.50 ⟺ P = 0.25 — exactamente el umbral asimétrico del short (§8.8)
    assert probability_from("SELL", 0.50) == 0.25
    direction, conf = _prob_to_signal(0.25)
    assert direction == "SELL"
    assert conf == pytest.approx(0.50, abs=1e-6)


def test_probability_hold_is_center():
    assert probability_from("HOLD", 0.0) == 0.5


# ── multiscale_signal (con bronze monkeypatcheado) ────────────────────────────


def _gold(symbol="BTC/USDT", hurst=0.55, ret_24h=0.01, garch_vol=0.005):
    return {
        "symbol": symbol,
        "timeframe": "1h",
        "ts": "2026-07-01T00:00:00+00:00",
        "regime": "trending",
        "regime_conf": 0.7,
        "features": {"hurst": hurst, "garch_vol": garch_vol, "returns_24h": ret_24h},
    }


def test_multiscale_signal_buy(monkeypatch):
    monkeypatch.setattr(
        "src.brain.quant_rule._past_returns", lambda *a, **k: [0.05, 0.10, 0.20, 0.40]
    )
    qs = multiscale_signal(_gold())
    assert qs.direction == "BUY"
    assert qs.confidence == 0.95
    assert qs.raw_probability == 0.975
    assert qs.size_usd > 0
    assert qs.model_version == "multimom-h6"
    assert set(qs.features_used) == {f"mom_{lb}h" for lb in MULTISCALE_LOOKBACKS}


def test_multiscale_signal_hold_has_zero_size(monkeypatch):
    monkeypatch.setattr(
        "src.brain.quant_rule._past_returns", lambda *a, **k: [0.05, -0.05, 0.05, -0.05]
    )
    qs = multiscale_signal(_gold())
    assert qs.direction == "HOLD"
    assert qs.size_usd == 0.0
    assert qs.raw_probability == 0.5


# ── quant_core_node: champion + gate de short + shadow ────────────────────────


def _node_state(gold_signals):
    return {"gold_signals": gold_signals, "symbols": [g["symbol"] for g in gold_signals]}


def test_node_emits_champion_and_shadow_vectors(monkeypatch):
    from src.brain.agents.quant import quant_core_node

    monkeypatch.setattr(
        "src.brain.quant_rule._past_returns", lambda *a, **k: [0.05, 0.10, 0.20, 0.40]
    )
    state = _node_state([_gold("BTC/USDT"), _gold("ETH/USDT")])
    out = quant_core_node(state)

    assert len(out["quant_signals"]) == 2
    assert all(s["direction"] == "BUY" for s in out["quant_signals"])
    assert all("multimom" in s["rationale"] for s in out["quant_signals"])
    assert out["quant_signal"]["direction"] == "BUY"

    # shadow = challenger ML + variante vol-target del campeón (capa de riesgo H10.3)
    shadow_ml = [s for s in out["shadow_signals"] if s["model"] in ("lightgbm", "heuristic-5f")]
    shadow_vt = [s for s in out["shadow_signals"] if s["model"] == "champion-voltarget25"]
    assert len(shadow_ml) == 2
    assert len(shadow_vt) == 2
    for ss in shadow_ml:
        assert ss["direction"] in ("BUY", "SELL", "HOLD")
        assert "raw_probability" in ss
    for ss in shadow_vt:
        assert ss["direction"] == "BUY"  # dirección del campeón, intacta


def test_node_short_gate_degrades_without_bear_regime(monkeypatch):
    from src.brain.agents.quant import quant_core_node

    monkeypatch.setattr(
        "src.brain.quant_rule._past_returns", lambda *a, **k: [-0.05, -0.10, -0.20, -0.40]
    )
    # Hurst < 0.5 (mean-reverting) → el short NO se confirma → HOLD
    state = _node_state([_gold("BTC/USDT", hurst=0.40, ret_24h=-0.02)])
    out = quant_core_node(state)
    assert out["quant_signals"][0]["direction"] == "HOLD"
    assert out["quant_signals"][0]["confidence"] == 0.0
    assert out["quant_signals"][0]["size_usd"] == 0.0


def test_node_short_survives_with_bear_confirmation(monkeypatch):
    from src.brain.agents.quant import quant_core_node

    monkeypatch.setattr(
        "src.brain.quant_rule._past_returns", lambda *a, **k: [-0.05, -0.10, -0.20, -0.40]
    )
    # Hurst ≥ 0.5 + drift 24h negativo + conf 0.95 ≥ 0.50 → short confirmado
    state = _node_state([_gold("BTC/USDT", hurst=0.60, ret_24h=-0.02)])
    out = quant_core_node(state)
    assert out["quant_signals"][0]["direction"] == "SELL"
    assert out["quant_signals"][0]["confidence"] == 0.95


def test_node_empty_gold_returns_empty_vectors():
    from src.brain.agents.quant import quant_core_node

    out = quant_core_node({"gold_signals": [], "symbols": []})
    assert out["quant_signals"] == []
    assert out["shadow_signals"] == []
    assert out["quant_signal"]["direction"] == "HOLD"


# ── persistencia shadow ───────────────────────────────────────────────────────


def test_persist_shadow_signals_roundtrip(tmp_path, monkeypatch):
    import duckdb

    from src.brain.shadow import persist_shadow_signals

    db = str(tmp_path / "shadow_test.duckdb")
    monkeypatch.setenv("HERMES_DUCKDB_PATH", db)

    rows = [
        {
            "model": "heuristic-5f",
            "symbol": "BTC/USDT",
            "direction": "HOLD",
            "confidence": 0.0,
            "raw_probability": 0.5,
            "size_usd": 0.0,
        },
        {
            "model": "heuristic-5f",
            "symbol": "ETH/USDT",
            "direction": "BUY",
            "confidence": 0.4,
            "raw_probability": 0.7,
            "size_usd": 0.04,
        },
    ]
    assert persist_shadow_signals("run-123", rows) == 2

    con = duckdb.connect(db)
    got = con.execute(
        "SELECT run_id, model, symbol, direction FROM shadow_signals ORDER BY symbol"
    ).fetchall()
    con.close()
    assert len(got) == 2
    assert got[0] == ("run-123", "heuristic-5f", "BTC/USDT", "HOLD")
    assert got[1][3] == "BUY"


def test_persist_shadow_empty_is_noop(tmp_path, monkeypatch):
    from src.brain.shadow import persist_shadow_signals

    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "noop.duckdb"))
    assert persist_shadow_signals("run-456", []) == 0
