"""Unit tests for the dashboard FastAPI app — routing, snapshot, template render.

The model-heavy /api/explain path is not exercised here (covered manually); these
tests use a synthetic snapshot and stay fast + offline.
"""
import json

import pytest
from fastapi.testclient import TestClient

from src.dashboard import app as dash_app

SNAPSHOT = {
    "generated_at": "2026-06-28T00:00:00+00:00",
    "symbols": ["BTC/USDT"],
    "timeframe": "1h",
    "shap": {
        "available": True,
        "symbols": {
            "BTC/USDT": {
                "ts": "2026-06-27T00:00:00",
                "regime": "volatile",
                "explanation": {
                    "prediction": {"direction": "HOLD", "probability": 0.49, "confidence": 0.0},
                    "base_value": 0.02,
                    "top_features": [{"feature": "momentum_1h", "shap_value": 0.05, "feature_value": 0.1}],
                    "waterfall": [{"label": "momentum_1h", "value": 0.05}],
                },
            }
        },
    },
    "cost": {"available": True, "total_usd": 0.0069, "runs": 1, "unlogged_runs": 0,
             "budget_usd": 150.0, "recent": []},
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
    assert "Explicabilidad SHAP" in r.text
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
