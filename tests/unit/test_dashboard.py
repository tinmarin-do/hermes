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


# ── /api/live — tile en vivo (read-only, informativo) ─────────────────────────


class _FakeLiveExchange:
    """fetch_balance + fetch_ticker mínimos para el tile en vivo."""

    def fetch_balance(self):
        return {
            "USDT": {"free": 100.0, "total": 100.0},
            "USD": {"free": 50.0, "total": 50.0},
            "SOL": {"free": 2.0, "total": 2.0},
            "LINK": {"free": 10.0, "total": 10.0},
        }

    def fetch_ticker(self, pair):
        # SOL/USDT=$80 · LINK/USD=$9 (verifica el mapping al par del venue)
        return {"last": {"SOL/USDT": 80.0, "LINK/USD": 9.0}[pair]}


@pytest.fixture
def live_client(client_with_snapshot, monkeypatch):
    monkeypatch.setattr(dash_app, "_live_exchange", lambda: _FakeLiveExchange())
    dash_app._live_cache.update(ts=0.0, data=None)  # sin cache entre tests
    return client_with_snapshot


def test_api_live_computes_equity_and_weights(live_client):
    r = live_client.get("/api/live")
    assert r.status_code == 200
    live = r.json()
    # cash 150 + SOL 2×80 + LINK 10×9 = 400
    assert live["equity_usd"] == 400.0
    assert live["cash_usd"] == 150.0
    syms = {p["symbol"]: p for p in live["positions"]}
    assert syms["SOL/USDT"]["value_usd"] == 160.0
    assert syms["LINK/USDT"]["value_usd"] == 90.0  # canónico, precio del par /USD
    assert syms["SOL/USDT"]["weight"] == pytest.approx(0.4)
    # delta vs snapshot oficial (equity_then=1.05 del SNAPSHOT sintético)
    assert live["vs_snapshot"]["equity_then"] == 1.05
    assert live["vs_snapshot"]["delta_usd"] == pytest.approx(398.95)
    assert "1 punto/día" in live["note"]


def test_api_live_503_without_readonly_creds(client_with_snapshot, monkeypatch):
    monkeypatch.delenv("BITSO_RO_KEY", raising=False)
    monkeypatch.delenv("BITSO_RO_SECRET", raising=False)
    dash_app._live_cache.update(ts=0.0, data=None)
    r = client_with_snapshot.get("/api/live")
    assert r.status_code == 503
    assert "read-only" in r.json()["detail"]


def test_index_renders_live_card(client_with_snapshot):
    r = client_with_snapshot.get("/")
    assert 'id="live-card"' in r.text
    assert 'id="live-refresh"' in r.text
    assert 'id="live-chart"' in r.text  # la GRÁFICA de performance (pedido 2026-07-04)


# ── /api/check-drawdown — watchdog intradía ────────────────────────────────────


@pytest.fixture
def watchdog_client(tmp_path, monkeypatch):
    """Live fake equity=400 vs snapshot equity=500 → delta_pct=−0.20 (breach a −3%)."""
    snap_data = dict(SNAPSHOT)
    snap_data["portfolio"] = {**SNAPSHOT["portfolio"], "equity_usd": 500.0}
    snap = tmp_path / "snapshot.json"
    snap.write_text(json.dumps(snap_data))
    monkeypatch.setattr(dash_app, "SNAPSHOT_PATH", snap)
    monkeypatch.setattr(dash_app, "_live_exchange", lambda: _FakeLiveExchange())
    dash_app._live_cache.update(ts=0.0, data=None)

    calls = {"claim": 0, "run": 0, "release": 0}

    def _bump(key, ret=None):
        def _f():
            calls[key] += 1
            return ret

        return _f

    monkeypatch.setattr(dash_app, "_claim_rerun_marker", _bump("claim", True))
    monkeypatch.setattr(dash_app, "_run_emergency_job", _bump("run"))
    monkeypatch.setattr(dash_app, "_release_rerun_marker", _bump("release"))
    monkeypatch.setenv("HERMES_EMERGENCY_JOB", "projects/p/locations/l/jobs/hermes-emergency-run")
    monkeypatch.setenv("HERMES_DRAWDOWN_ALERT_PCT", "0.03")
    client = TestClient(dash_app.app)
    return client, calls


def test_check_drawdown_breach_triggers_rerun_and_logs(watchdog_client, capsys):
    client, calls = watchdog_client
    r = client.post("/api/check-drawdown")
    assert r.status_code == 200
    body = r.json()
    assert body["breach"] is True
    assert body["delta_pct"] == pytest.approx(-0.20)
    assert body["rerun"] == "triggered"
    assert calls["run"] == 1
    out = capsys.readouterr().out
    assert "DRAWDOWN_BREACH" in out
    logged = json.loads([ln for ln in out.splitlines() if "DRAWDOWN_BREACH" in ln][0])
    assert logged["severity"] == "ERROR"
    assert logged["threshold"] == 0.03


def test_check_drawdown_no_breach(client_with_snapshot, monkeypatch, capsys):
    # snapshot 1.05 vs live 400 → delta MUY positivo: jamás breach
    monkeypatch.setattr(dash_app, "_live_exchange", lambda: _FakeLiveExchange())
    dash_app._live_cache.update(ts=0.0, data=None)
    r = client_with_snapshot.post("/api/check-drawdown")
    assert r.status_code == 200
    assert r.json()["breach"] is False
    assert r.json()["rerun"] == "not-applicable"
    assert "DRAWDOWN_BREACH" not in capsys.readouterr().out


def test_check_drawdown_cooldown_still_logs(watchdog_client, monkeypatch, capsys):
    client, calls = watchdog_client
    monkeypatch.setattr(dash_app, "_claim_rerun_marker", lambda: False)
    r = client.post("/api/check-drawdown")
    assert r.json()["rerun"] == "cooldown"
    assert calls["run"] == 0  # sin re-run…
    assert "DRAWDOWN_BREACH" in capsys.readouterr().out  # …pero el email SIEMPRE


def test_check_drawdown_threshold_env(watchdog_client, monkeypatch):
    client, calls = watchdog_client
    monkeypatch.setenv("HERMES_DRAWDOWN_ALERT_PCT", "0.5")  # −20% no alcanza −50%
    dash_app._live_cache.update(ts=0.0, data=None)
    r = client.post("/api/check-drawdown")
    assert r.json()["breach"] is False
    assert calls["run"] == 0


def test_check_drawdown_200_when_bitso_down(client_with_snapshot, monkeypatch):
    monkeypatch.delenv("BITSO_RO_KEY", raising=False)
    monkeypatch.setattr(dash_app, "_live_exchange", lambda: None)
    dash_app._live_cache.update(ts=0.0, data=None)
    r = client_with_snapshot.post("/api/check-drawdown")
    assert r.status_code == 200  # infraestructura caída ≠ breach
    assert r.json()["breach"] is False
    assert "error" in r.json()


def test_check_drawdown_trigger_failure_releases_marker(watchdog_client, monkeypatch):
    client, calls = watchdog_client

    def _boom():
        raise RuntimeError("scheduler api down")

    monkeypatch.setattr(dash_app, "_run_emergency_job", _boom)
    r = client.post("/api/check-drawdown")
    assert r.json()["rerun"].startswith("error")
    assert calls["release"] == 1  # cupo devuelto


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
