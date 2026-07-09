"""Unit tests — src/brain/server.py `/run` endpoint (gate execute, hallazgo 2026-07-08)."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client(monkeypatch):
    import scripts.daily_run as daily_run_module
    import src.brain.state_sync as state_sync_module
    from src.brain.server import app

    monkeypatch.setattr(state_sync_module, "download_state", lambda: "/tmp/fake.duckdb")
    monkeypatch.setattr(state_sync_module, "upload_state", lambda: None)

    captured: dict = {}

    def fake_main(force: bool = False, execute: bool = True) -> int:
        captured["force"] = force
        captured["execute"] = execute
        return 0

    monkeypatch.setattr(daily_run_module, "main", fake_main)

    return TestClient(app), captured


def test_run_defaults_to_execute_true(client):
    tc, captured = client
    resp = tc.post("/run")
    assert resp.status_code == 200
    assert captured["execute"] is True
    body = resp.json()
    assert body["execute"] is True
    assert body["rc"] == 0


def test_run_execute_false_passthrough(client):
    tc, captured = client
    resp = tc.post("/run?execute=false")
    assert resp.status_code == 200
    assert captured["execute"] is False
    assert resp.json()["execute"] is False


def test_run_force_and_execute_both_passthrough(client):
    tc, captured = client
    resp = tc.post("/run?force=true&execute=false")
    assert resp.status_code == 200
    assert captured["force"] is True
    assert captured["execute"] is False
