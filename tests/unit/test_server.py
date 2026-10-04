"""Unit tests — src/brain/server.py `/run` endpoint (gate execute, hallazgo 2026-07-08)."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client(monkeypatch, tmp_path):
    import scripts.daily_run as daily_run_module
    import src.brain.state_sync as state_sync_module
    from src.brain.server import app

    fake_db_path = str(tmp_path / "fake.duckdb")
    monkeypatch.setattr(state_sync_module, "download_state", lambda: fake_db_path)
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


# ─────────────────────────────────────────────────────────────────────────────
# Persistencia del estado ante corrida fallida — cicatriz 2026-10-03.
# upload_state() vivía en el camino feliz: cualquier excepción de daily_main
# saltaba al except y el DuckDB de /tmp moría con el contenedor. Las órdenes
# que esa corrida YA había mandado al venue (irreversibles) desaparecían del
# ledger. La forensia halló ~$375 de ventas reales sin registrar.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def client_with_sync_spy(monkeypatch, tmp_path):
    import scripts.daily_run as daily_run_module
    import src.brain.state_sync as state_sync_module
    from src.brain.server import app

    calls = {"upload": 0, "recover": 0}
    monkeypatch.setattr(state_sync_module, "download_state", lambda: str(tmp_path / "f.duckdb"))
    monkeypatch.setattr(
        state_sync_module, "upload_state", lambda: calls.__setitem__("upload", calls["upload"] + 1)
    )
    monkeypatch.setattr(
        state_sync_module,
        "recover_fills",
        lambda con: calls.__setitem__("recover", calls["recover"] + 1),
    )
    return TestClient(app, raise_server_exceptions=False), calls, daily_run_module, monkeypatch


def test_upload_state_corre_aunque_la_corrida_reviente(client_with_sync_spy):
    """EL BUG: una corrida que truena pudo haber mandado órdenes reales antes."""
    client, calls, daily_run_module, monkeypatch = client_with_sync_spy

    def boom(force=False, execute=True):
        raise RuntimeError("el comité explotó a mitad")

    monkeypatch.setattr(daily_run_module, "main", boom)

    r = client.post("/run")

    assert r.status_code == 500
    assert calls["upload"] == 1, "el estado DEBE subirse aunque la corrida falle"


def test_recover_fills_corre_antes_de_decidir(client_with_sync_spy):
    """El libro se repara ANTES de que el allocator calcule deltas contra él."""
    client, calls, daily_run_module, monkeypatch = client_with_sync_spy
    order: list[str] = []
    monkeypatch.setattr(
        daily_run_module, "main", lambda force=False, execute=True: order.append("run") or 0
    )
    import src.brain.state_sync as state_sync_module

    monkeypatch.setattr(state_sync_module, "recover_fills", lambda con: order.append("recover"))

    client.post("/run")

    assert order == ["recover", "run"]


def test_camino_feliz_sigue_subiendo_una_sola_vez(client_with_sync_spy):
    client, calls, daily_run_module, monkeypatch = client_with_sync_spy
    monkeypatch.setattr(daily_run_module, "main", lambda force=False, execute=True: 0)
    r = client.post("/run")
    assert r.status_code == 200
    assert calls["upload"] == 1
