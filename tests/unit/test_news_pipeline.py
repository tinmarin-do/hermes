"""Unit tests — pipeline de noticias (Fase 4): partes puras, sin red ni modelos.

La config de clustering es la decidida en el lab Fase 4.0 (MiniLM-L6 + HDBSCAN
mcs=10/ms=5 sobre UMAP 10d). El etiquetado es heurístico por default ($0 LLM).
"""

import numpy as np
import pytest

from src.brain.news_verify import apply_news_modifier
from src.data.silver.news_transform import (
    _compute_trust_scores,
    _hdbscan_params,
    _heuristic_label,
    _sentiment_from_cluster,
)

pytestmark = pytest.mark.unit


# ── parámetros HDBSCAN (decisión del lab + guarda para batches chicos) ────────


def test_hdbscan_params_use_decided_values_at_scale():
    assert _hdbscan_params(391) == (10, 5)  # el n del lab → exactamente lo decidido
    assert _hdbscan_params(100) == (10, 5)
    assert _hdbscan_params(50) == (10, 5)


def test_hdbscan_params_shrink_for_small_batches():
    mcs, ms = _hdbscan_params(20)
    assert mcs == 4  # 20 // 5
    assert ms <= mcs
    mcs, ms = _hdbscan_params(8)
    assert mcs == 3  # piso de HDBSCAN
    assert ms <= mcs


# ── etiquetado heurístico (taxonomía fija de news_verify) ─────────────────────


def test_heuristic_labels_prd_taxonomy():
    assert _heuristic_label("Bridge exploited for $2.1M, funds stolen") == "hack"
    assert _heuristic_label("SEC lawsuit against exchange; new regulation") == "regulatory"
    assert _heuristic_label("Ethereum upgrade: EIP goes live after fork") == "protocol_upgrade"
    assert _heuristic_label("Fed holds interest rate; CPI inflation cools") == "macro"
    assert _heuristic_label("Whale transfer: 40,000 BTC moved on-chain") == "whale_movement"
    assert _heuristic_label("Token rallies as traders turn bullish") == "market_sentiment"


def test_sentiment_maps_to_taxonomy():
    assert _sentiment_from_cluster("protocol_upgrade") > 0
    assert _sentiment_from_cluster("hack") < 0
    assert _sentiment_from_cluster("macro") == 0.0


# ── trust score: corroboración multi-fuente (PRD §8.7.1) ──────────────────────


def test_trust_corroborated_story_beats_single_source():
    # 3 ítems casi idénticos (2 fuentes distintas) + 1 aislado
    base = np.array([1.0, 0.0, 0.0])
    near = np.array([0.99, 0.14, 0.0])
    far = np.array([0.0, 1.0, 0.0])
    emb = np.vstack([base, near / np.linalg.norm(near), far])
    items = [
        {"source": "coindesk_rss"},
        {"source": "cointelegraph_rss"},
        {"source": "decrypt_rss"},
    ]
    scores = _compute_trust_scores(items, emb)
    assert scores[0] > scores[2]  # corroborada > aislada
    assert scores[1] > scores[2]


def test_trust_onchain_source_has_highest_base():
    emb = np.eye(2)
    items = [{"source": "whale_alert"}, {"source": "decrypt_rss"}]
    scores = _compute_trust_scores(items, emb)
    assert scores[0] > scores[1]  # on-chain > editorial (menos manipulable)


# ── news_verify: las noticias solo modulan, jamás originan (§8.7.2) ───────────


def _signal(cluster=None, trust=0.9):
    feats = {}
    if cluster is not None:
        feats = {"news_cluster": cluster, "news_sentiment_score": 0.0, "trust_score": trust}
    return {"features": feats}


def test_news_never_turns_hold_into_trade():
    conf, note = apply_news_modifier(0.8, _signal("protocol_upgrade"), "HOLD")
    assert conf == 0.8  # HOLD queda intacto pase lo que pase
    assert "neutral" in note


def test_news_confirming_boosts_capped():
    conf, _ = apply_news_modifier(0.8, _signal("protocol_upgrade"), "BUY")
    assert conf == pytest.approx(0.96)  # ×1.2, cap 1.0


def test_news_contradicting_cuts_confidence():
    conf, note = apply_news_modifier(0.8, _signal("hack"), "BUY")
    assert conf == pytest.approx(0.48)  # ×0.6
    assert "contradice" in note


def test_low_trust_news_discounted_further():
    conf_high, _ = apply_news_modifier(0.8, _signal("hack", trust=0.9), "BUY")
    conf_low, note = apply_news_modifier(0.8, _signal("hack", trust=0.2), "BUY")
    assert conf_low < conf_high  # trust bajo descuenta extra
    assert "trust bajo" in note


def test_no_news_is_neutral():
    conf, note = apply_news_modifier(0.8, _signal(None), "BUY")
    assert conf == 0.8
    assert "sin contexto" in note
