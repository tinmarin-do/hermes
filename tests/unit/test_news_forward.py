"""Unit tests — H10.4 logging forward de noticias (protocolo pre-registrado).

Sin red, sin LLM, $0 — DuckDB temporal sembrado a mano. El protocolo: cada
corrida persiste el vector por símbolo y puntúa las filas cuyo horizonte cerró.
"""

import json
from datetime import datetime, timedelta

import pytest

from src.brain.news_forward import (
    GATE_DAYS,
    build_news_vector,
    forward_status,
    log_news_forward,
    score_pending,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 7, 7, 14, 0, 0)


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "nf.duckdb"))
    from src.data.db import get_connection

    c = get_connection()
    yield c
    c.close()


def _seed_news(con, rows):
    """rows: (id, symbols_json, hours_ago, cluster_label, is_noise, trust, injection)."""
    for nid, syms, hours_ago, label, noise, trust, inj in rows:
        ts = NOW - timedelta(hours=hours_ago)
        con.execute(
            "INSERT INTO bronze_news (id, source, title, published_at, symbols, "
            "injection_flag, ingested_at) VALUES (?, 's', 't', ?, ?, ?, ?)",
            [nid, ts, json.dumps(syms), inj, ts],
        )
        if label is not None or noise:
            con.execute(
                "INSERT INTO silver_news_clusters (id, source, published_at, cluster_id, "
                "cluster_label, is_noise, trust_score, computed_at) "
                "VALUES (?, 's', ?, ?, ?, ?, ?, ?)",
                [nid, ts, -1 if noise else 1, label, noise, trust, ts],
            )


def _seed_prices(con, symbol, closes, start=NOW, step_h=1):
    for i, c in enumerate(closes):
        ts = start + timedelta(hours=i * step_h)
        con.execute(
            "INSERT INTO bronze_ohlcv VALUES (?, '1h', ?, ?, ?, ?, ?, 1.0, ?)",
            [symbol, ts, c, c, c, c, ts],
        )


# ── build_news_vector ──────────────────────────────────────────────────────────


def test_vector_counts_novelty_and_sentiment(con):
    _seed_news(
        con,
        [
            ("n1", ["BTC"], 2, "listing", False, 0.8, False),  # bullish, trust alto
            ("n2", ["BTC"], 3, "regulatory", False, 0.4, False),  # bearish, trust bajo
            ("n3", ["BTC"], 4, None, True, 0.0, False),  # ruido → novelty
            ("n4", ["BTC"], 5, None, False, None, False),  # sin clusterizar → novelty
        ],
    )
    v = build_news_vector(con, "BTC/USDT", NOW)
    assert v["n_headlines"] == 4
    assert v["novelty_frac"] == pytest.approx(0.5)  # 2 de 4 sin cluster
    # (0.6×0.8 + (−0.4)×0.4) / (0.8+0.4) = 0.32/1.2
    assert v["sentiment_tw"] == pytest.approx(0.2667, abs=1e-3)
    assert v["clusters"] == {"listing": 1, "regulatory": 1}


def test_vector_ignores_old_injected_and_other_symbols(con):
    _seed_news(
        con,
        [
            ("n1", ["BTC"], 30, "listing", False, 0.8, False),  # fuera de la ventana 24h
            ("n2", ["BTC"], 2, "hack", False, 0.9, True),  # inyección detectada
            ("n3", ["ETH"], 2, "listing", False, 0.8, False),  # otro símbolo
        ],
    )
    v = build_news_vector(con, "BTC/USDT", NOW)
    assert v["n_headlines"] == 0
    assert v["novelty_frac"] is None
    assert v["sentiment_tw"] == 0.0


# ── log + score ────────────────────────────────────────────────────────────────


def test_log_persists_one_row_per_symbol(con):
    con.close()
    res = log_news_forward("run-1", ["BTC/USDT", "ETH/USDT"])
    assert res["logged"] == 2
    from src.data.db import get_connection

    c = get_connection()
    rows = c.execute("SELECT symbol, ret_24h FROM news_forward_log ORDER BY symbol").fetchall()
    c.close()
    assert [r[0] for r in rows] == ["BTC/USDT", "ETH/USDT"]
    assert all(r[1] is None for r in rows)  # sin puntuar: el futuro no llegó


def test_log_idempotent_per_run_symbol(con):
    con.close()
    log_news_forward("run-1", ["BTC/USDT"])
    log_news_forward("run-1", ["BTC/USDT"])  # replace, no duplica
    from src.data.db import get_connection

    c = get_connection()
    n = c.execute("SELECT COUNT(*) FROM news_forward_log").fetchone()[0]
    c.close()
    assert n == 1


def test_scoring_fills_closed_horizons_only(con):
    from src.brain.news_forward import _ensure_table

    _ensure_table(con)
    as_of = NOW - timedelta(hours=30)  # 24h cerró, 7d no
    con.execute(
        "INSERT INTO news_forward_log VALUES ('r0', 'BTC/USDT', ?, 1, 0.0, 0.5, '{}', "
        "NULL, NULL, NULL, ?)",
        [as_of, as_of],
    )
    # precios: 100 en as_of, 110 a las 24h, datos hasta +30h (7d incompleto)
    _seed_prices(con, "BTC/USDT", [100.0 + i / 3 for i in range(31)], start=as_of)
    updated = score_pending(con, NOW)
    assert updated == 1
    ret24, ret7, scored_at = con.execute(
        "SELECT ret_24h, ret_7d, scored_at FROM news_forward_log"
    ).fetchone()
    assert ret24 == pytest.approx(0.08, abs=1e-6)  # 108/100 − 1
    assert ret7 is None  # horizonte 7d sigue abierto
    assert scored_at is None  # solo se sella cuando AMBOS horizontes cierran


def test_scoring_completes_7d_and_seals(con):
    from src.brain.news_forward import _ensure_table

    _ensure_table(con)
    as_of = NOW - timedelta(hours=200)  # ambos horizontes cerrados
    con.execute(
        "INSERT INTO news_forward_log VALUES ('r0', 'BTC/USDT', ?, 1, 0.0, 0.5, '{}', "
        "NULL, NULL, NULL, ?)",
        [as_of, as_of],
    )
    # índices 0-23 = 100 (as_of), 24-167 = 105 (cierra 24h), 168+ = 90 (cierra 7d)
    _seed_prices(con, "BTC/USDT", [100.0] * 24 + [105.0] * 144 + [90.0] * 40, start=as_of)
    assert score_pending(con, NOW) == 1
    ret24, ret7, scored_at = con.execute(
        "SELECT ret_24h, ret_7d, scored_at FROM news_forward_log"
    ).fetchone()
    assert ret24 == pytest.approx(0.05)  # close(+24h)=105
    assert ret7 == pytest.approx(-0.10)  # close(+168h)=90
    assert scored_at is not None


# ── forward_status: el gate de 90 días ─────────────────────────────────────────


def test_status_tracks_gate_progress(con):
    from src.brain.news_forward import _ensure_table

    _ensure_table(con)
    for d in range(3):
        ts = NOW - timedelta(days=d)
        con.execute(
            "INSERT INTO news_forward_log VALUES (?, 'BTC/USDT', ?, 2, 0.5, 0.1, '{}', "
            "NULL, NULL, NULL, ?)",
            [f"r{d}", ts, ts],
        )
    con.close()
    st = forward_status()
    assert st["available"] is True
    assert st["n_days"] == 3
    assert st["gate_days"] == GATE_DAYS
    assert st["gate_reached"] is False
    assert st["latest"][0]["symbol"] == "BTC/USDT"
    assert "90" in st["note"]
