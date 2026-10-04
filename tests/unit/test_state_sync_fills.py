"""Unit tests — bitácora durable de fills (src/brain/state_sync.py).

Cicatriz 2026-10-03: el DuckDB operacional vive en /tmp y solo llega al bucket
cuando la corrida TERMINA. Entre que el venue acepta un fill (irreversible) y
el upload hay una ventana donde el dinero ya se movió y el registro no existe.
La forensia encontró ~$375 de ventas reales ausentes del ledger.

Bucket FAKE en memoria — sin red, sin GCS, $0.
"""

import json

import pytest

from src.brain import state_sync

pytestmark = pytest.mark.unit


class FakeBlob:
    def __init__(self, store: dict, name: str):
        self._store, self.name = store, name

    def upload_from_string(self, data, content_type=None):
        self._store[self.name] = data

    def download_as_bytes(self):
        return self._store[self.name].encode()


class FakeBucket:
    def __init__(self, store: dict):
        self._store = store

    def blob(self, name):
        return FakeBlob(self._store, name)

    def list_blobs(self, prefix=""):
        return [FakeBlob(self._store, n) for n in sorted(self._store) if n.startswith(prefix)]


@pytest.fixture
def gcs(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setenv("HERMES_STATE_BUCKET", "fake-bucket")
    monkeypatch.setattr(state_sync, "_bucket", lambda: FakeBucket(store))
    return store


def _fill(oid="ord-1", symbol="BTC/USDT", action="SELL", qty=0.01):
    return {
        "order_id": oid,
        "run_id": "run-abc",
        "symbol": symbol,
        "action": action,
        "quantity": qty,
        "price": 80000.0,
        "status": "FILLED",
        "filled_at": "2026-08-24T14:19:00",
        "created_at": "2026-08-24T14:19:00",
        "cost_usd": 800.0,
        "fee_usd": 2.88,
    }


def test_journal_fill_escribe_un_objeto_por_orden(gcs):
    state_sync.journal_fill(_fill())
    assert "fills/2026-08-24/ord-1.json" in gcs
    assert json.loads(gcs["fills/2026-08-24/ord-1.json"])["symbol"] == "BTC/USDT"


def test_journal_fill_es_noop_sin_bucket(monkeypatch):
    """Modo local: no hay bucket y no debe tronar."""
    monkeypatch.delenv("HERMES_STATE_BUCKET", raising=False)
    state_sync.journal_fill(_fill())  # no levanta


def test_journal_fill_nunca_levanta_aunque_falle_gcs(monkeypatch, capsys):
    """Que la bitácora falle NO puede tumbar una ejecución en curso."""
    monkeypatch.setenv("HERMES_STATE_BUCKET", "fake-bucket")

    def boom():
        raise RuntimeError("GCS caído")

    monkeypatch.setattr(state_sync, "_bucket", boom)
    state_sync.journal_fill(_fill())  # no levanta
    assert "FILL_JOURNAL_FAILED" in capsys.readouterr().out


def _con(tmp_path):
    """DuckDB aislado con el esquema real de execution_orders (mismo orden de columnas)."""
    import duckdb

    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    con.execute("""
        CREATE TABLE execution_orders (
            order_id   VARCHAR PRIMARY KEY,
            run_id     VARCHAR NOT NULL,
            symbol     VARCHAR NOT NULL,
            action     VARCHAR NOT NULL,
            quantity   DOUBLE NOT NULL,
            price      DOUBLE,
            status     VARCHAR NOT NULL DEFAULT 'PENDING',
            filled_at  TIMESTAMP,
            created_at TIMESTAMP NOT NULL,
            error      VARCHAR,
            cost_usd   DOUBLE DEFAULT 0,
            fee_usd    DOUBLE DEFAULT 0
        )
    """)
    return con


def test_recover_fills_devuelve_al_ledger_lo_que_se_perdio(gcs, tmp_path, capsys):
    """EL CASO REAL: la corrida murió tras ejecutar, el fill vive solo en GCS."""
    state_sync.journal_fill(_fill(oid="perdida-1"))
    state_sync.journal_fill(_fill(oid="perdida-2", symbol="ETH/USDT"))

    con = _con(tmp_path)
    assert state_sync.recover_fills(con) == 2

    rows = con.execute("SELECT order_id, symbol FROM execution_orders ORDER BY 1").fetchall()
    assert rows == [("perdida-1", "BTC/USDT"), ("perdida-2", "ETH/USDT")]
    assert "FILLS_RECOVERED" in capsys.readouterr().out


def test_recover_fills_es_idempotente(gcs, tmp_path):
    """Correrlo dos veces no duplica ni re-reporta."""
    state_sync.journal_fill(_fill(oid="ord-x"))
    con = _con(tmp_path)
    assert state_sync.recover_fills(con) == 1
    assert state_sync.recover_fills(con) == 0
    assert con.execute("SELECT count(*) FROM execution_orders").fetchone()[0] == 1


def test_recover_fills_no_toca_lo_que_ya_estaba(gcs, tmp_path):
    """Un fill que SÍ se grabó no se recupera ni se pisa."""
    state_sync.journal_fill(_fill(oid="ya-estaba"))
    con = _con(tmp_path)
    con.execute(
        "INSERT INTO execution_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            "ya-estaba",
            "r",
            "BTC/USDT",
            "SELL",
            0.01,
            80000.0,
            "FILLED",
            "2026-08-24 14:19:00",
            "2026-08-24 14:19:00",
            None,
            800.0,
            2.88,
        ],
    )
    assert state_sync.recover_fills(con) == 0


def test_recover_fills_noop_sin_bucket(monkeypatch, tmp_path):
    monkeypatch.delenv("HERMES_STATE_BUCKET", raising=False)
    assert state_sync.recover_fills(_con(tmp_path)) == 0
