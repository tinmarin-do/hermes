"""Unit tests for the dashboard FastAPI app — routing, snapshot, template render.

The model-heavy /api/explain path is not exercised here (covered manually); these
tests use a synthetic snapshot and stay fast + offline.
"""

import json

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dash_app

pytestmark = pytest.mark.unit

SNAPSHOT = {
    "generated_at": "2026-06-28T00:00:00+00:00",
    "symbols": ["BTC/USDT"],
    "timeframe": "1h",
    "portfolio": {
        "available": True,
        "budget_usd": 1.0,
        "balance_usd": 0.0,
        "equity_usd": 1.05,
        "cash_weight": 0.0,
        "rows": [
            {
                "symbol": "BTC/USDT",
                "side": "BUY",
                "market_value_usd": 1.05,
                "weight": 1.0,
                "target_weight": 0.9,
                "unrealized_pnl": 0.05,
                "realized_pnl": 0.0,
            }
        ],
        "champion_now": {
            "BTC/USDT": {
                "direction": "BUY",
                "confidence": 0.95,
                "momentum": {"mom_168h": 0.02, "mom_336h": 0.05, "mom_720h": 0.1, "mom_2160h": 0.3},
            }
        },
        "note": "test",
    },
    "equity": {
        "available": True,
        "series": [
            {"ts": "2026-07-01 00:00:00", "equity": 1.0},
            {"ts": "2026-07-02 00:00:00", "equity": 1.05},
        ],
        "metrics": {"n_points": 2, "total_return": 0.05, "max_drawdown": 0.0},
        "note": None,
    },
    "signals": {
        "available": True,
        "shadow_model": "lightgbm",
        "shadow_run": "40b2cb70",
        "rows": [
            {
                "symbol": "BTC/USDT",
                "champion": {"direction": "BUY", "confidence": 0.95},
                "shadow": {"direction": "HOLD", "confidence": 0.0, "probability": 0.49},
                "agree": False,
            }
        ],
        "history": [{"model": "lightgbm", "runs": 2, "signals": 8}],
        "note": "test",
    },
    "debate": {
        "available": True,
        "run_id": "40b2cb70-0000",
        "ts": "2026-07-02 00:00:00",
        "debate_verdict": "HOLD",
        "debate_confidence": 0.8,
        "risk_approved": True,
        "pm_action": "HOLD",
        "pm_rationale": "Debate verdict HOLD — PM brake.",
        "transcript": {"bull_argument": "b", "bear_argument": "o", "debate_rounds": []},
    },
    "shap": {
        "available": True,
        "symbols": {
            "BTC/USDT": {
                "ts": "2026-06-27T00:00:00",
                "regime": "volatile",
                "explanation": {
                    "prediction": {"direction": "HOLD", "probability": 0.49, "confidence": 0.0},
                    "base_value": 0.02,
                    "top_features": [
                        {"feature": "momentum_1h", "shap_value": 0.05, "feature_value": 0.1}
                    ],
                    "waterfall": [{"label": "momentum_1h", "value": 0.05}],
                },
            }
        },
    },
    "cost": {
        "available": True,
        "total_usd": 0.0069,
        "runs": 1,
        "unlogged_runs": 0,
        "budget_usd": 150.0,
        "recent": [],
    },
    "positions": {"available": True, "balance_usd": 500.0, "open": []},
}


@pytest.fixture
def client_with_snapshot(tmp_path, monkeypatch):
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(SNAPSHOT))
    monkeypatch.setattr(dash_app, "SNAPSHOT_PATH", snap)
    return TestClient(dash_app.app)


@pytest.fixture
def client_no_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(dash_app, "SNAPSHOT_PATH", tmp_path / "missing.json")
    return TestClient(dash_app.app)


def test_healthz(client_with_snapshot):
    r = client_with_snapshot.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_renders_shap_panel(client_with_snapshot):
    r = client_with_snapshot.get("/")
    assert r.status_code == 200
    assert "explicabilidad SHAP" in r.text  # ahora etiquetado como panel del challenger
    assert "/static/app.js" in r.text
    assert "No hay snapshot" not in r.text


def test_index_without_snapshot_shows_warning(client_no_snapshot):
    r = client_no_snapshot.get("/")
    assert r.status_code == 200
    assert "No hay snapshot" in r.text


def test_api_snapshot_returns_data(client_with_snapshot):
    r = client_with_snapshot.get("/api/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["shap"]["available"] is True
    assert "BTC/USDT" in body["shap"]["symbols"]
    assert body["cost"]["total_usd"] == 0.0069


def test_api_snapshot_404_without_snapshot(client_no_snapshot):
    r = client_no_snapshot.get("/api/snapshot")
    assert r.status_code == 404


def test_static_assets_served(client_with_snapshot):
    assert client_with_snapshot.get("/static/app.js").status_code == 200
    assert client_with_snapshot.get("/static/style.css").status_code == 200


def test_index_renders_new_panels(client_with_snapshot):
    r = client_with_snapshot.get("/")
    assert r.status_code == 200
    # El modo (paper / live · bitso) ya no está hardcodeado: lo llena el JS desde
    # el snapshot (susto 2026-07-04: el título decía "(paper)" con ejecución live).
    assert "(paper)" not in r.text
    assert 'id="pf-mode"' in r.text
    assert 'id="pos-mode"' in r.text
    assert "Equity curve" in r.text
    assert "Champion vs shadow" in r.text
    assert "Visor de debate" in r.text


def test_api_snapshot_has_fase3_panels(client_with_snapshot):
    body = client_with_snapshot.get("/api/snapshot").json()
    assert body["portfolio"]["equity_usd"] == 1.05
    assert len(body["equity"]["series"]) == 2
    assert body["signals"]["rows"][0]["agree"] is False
    assert body["debate"]["debate_verdict"] == "HOLD"


# ── Paneles de build contra DuckDB temporal (sin red, sin LLM) ─────────────────


@pytest.fixture
def build_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "dash.duckdb"))
    monkeypatch.setenv("HERMES_CAPITAL_USD", "1")
    return tmp_path


def test_portfolio_panel_empty_book(build_env):
    from src.dashboard.build import _portfolio_panel

    panel = _portfolio_panel("1h")
    assert panel["available"] is True
    assert panel["balance_usd"] == pytest.approx(1.0)
    assert panel["equity_usd"] == pytest.approx(1.0)
    assert panel["cash_weight"] == pytest.approx(1.0)


def test_equity_panel_accumulates_points(build_env):
    from src.dashboard.build import _equity_panel

    pf = {"available": True, "balance_usd": 1.0, "equity_usd": 1.0}
    first = _equity_panel(pf)
    assert first["available"] is True
    assert len(first["series"]) == 1
    assert first["metrics"] is None  # 1 punto → sin métricas, con nota honesta
    assert "arranca" in first["note"]

    second = _equity_panel({"available": True, "balance_usd": 0.5, "equity_usd": 1.1})
    assert len(second["series"]) == 2
    assert second["metrics"]["total_return"] == pytest.approx(0.1, abs=1e-6)
    assert "requieren más muestra" in second["note"]  # n<8 → sin Sharpe/PSR


def test_signals_panel_compares_champion_vs_shadow(build_env):
    from src.brain.shadow import persist_shadow_signals
    from src.dashboard.build import _signals_panel

    persist_shadow_signals(
        "run-x",
        [
            {
                "model": "lightgbm",
                "symbol": "BTC/USDT",
                "direction": "HOLD",
                "confidence": 0.0,
                "raw_probability": 0.49,
                "size_usd": 0.0,
            }
        ],
    )
    champion_now = {"BTC/USDT": {"direction": "BUY", "confidence": 0.95}}
    panel = _signals_panel(champion_now)
    assert panel["available"] is True
    assert panel["shadow_model"] == "lightgbm"
    assert panel["rows"][0]["agree"] is False
    assert panel["history"][0]["runs"] == 1


def test_debate_panel_roundtrip(build_env):
    from src.brain.transcript import latest_transcript, persist_transcript
    from src.dashboard.build import _debate_panel

    assert _debate_panel()["available"] is False  # sin corridas

    state = {
        "regime_summary": "BTC trending",
        "debate_verdict": "HOLD",
        "debate_confidence": 0.8,
        "risk_approved": True,
        "pm_decision": {"action": "HOLD", "rationale": "brake"},
        "bull_argument": "bull",
        "bear_argument": "bear",
        "debate_rounds": [{"round": 1}],
        "risk_synthesis": "ok",
        "quant_signals": [],
        "allocations": [],
    }
    persist_transcript("run-y", state)

    latest = latest_transcript()
    assert latest is not None and latest["run_id"] == "run-y"

    panel = _debate_panel()
    assert panel["available"] is True
    assert panel["debate_verdict"] == "HOLD"
    assert panel["transcript"]["bull_argument"] == "bull"
    assert panel["transcript"]["debate_rounds"] == [{"round": 1}]
