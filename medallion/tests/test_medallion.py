"""Tests offline del medallón: contrato, cuarentena, idempotencia y búsqueda.

Ninguno toca la red: el lote de Bronze se siembra con un RSS sintético y los
embeddings se sustituyen por un hash determinista.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from pydantic import ValidationError

from medallion import gold, silver
from medallion.contracts import NewsItem, natural_key
from medallion.db import get_connection

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item>
  <title>Bitcoin ETF inflows hit a record for the quarter</title>
  <link>https://example.com/nota-1</link>
  <description>Spot bitcoin funds absorbed more than a billion dollars
    this week according to filings.</description>
  <pubDate>Tue, 28 Jul 2026 12:00:00 GMT</pubDate>
</item>
<item>
  <title>Ethereum developers schedule the next network upgrade</title>
  <link>https://example.com/nota-2</link>
  <description>The upgrade bundles changes to staking withdrawals
    and execution layer fees.</description>
  <pubDate>Wed, 29 Jul 2026 09:30:00 GMT</pubDate>
</item>
<item>
  <title>Nota sin liga ni fecha, debe caer en cuarentena</title>
  <link></link>
  <description>Cuerpo suficientemente largo como para pasar el mínimo
    de caracteres del contrato.</description>
</item>
</channel></rss>"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDALLION_DUCKDB_PATH", str(tmp_path / "m.duckdb"))
    monkeypatch.setenv("MEDALLION_DATA_DIR", str(tmp_path / "medallion"))
    return tmp_path


def _sembrar(batch_id: str, payload: str = RSS) -> None:
    con = get_connection()
    con.execute(
        """INSERT INTO bronze_batches VALUES (?, 'coindesk', 'https://example.com/rss', ?,
                                              200, 'application/xml', ?, ?, ?, ?)
           ON CONFLICT (batch_id, source) DO NOTHING""",
        [
            batch_id,
            datetime.now(UTC).replace(tzinfo=None),
            len(payload),
            hashlib.sha256(payload.encode()).hexdigest(),
            f"bronze/{batch_id}/coindesk.xml",
            payload,
        ],
    )
    con.close()


# ───────────────────────────── contrato ─────────────────────────────
def _valida() -> dict:
    url = "https://example.com/ok"
    return {
        "news_id": natural_key("coindesk", url),
        "source": "coindesk",
        "title": "Un titular perfectamente válido",
        "url": url,
        "body": "Un cuerpo con más de cuarenta caracteres para pasar el contrato.",
        "published_at": datetime(2026, 7, 20, 12, 0),
        "symbols": ["BTC"],
    }


def test_contrato_acepta_registro_valido():
    assert NewsItem(**_valida()).news_id == natural_key("coindesk", "https://example.com/ok")


@pytest.mark.parametrize(
    ("campo", "valor", "loc"),
    [
        ("url", "no-es-una-url", "url"),
        ("body", "corto", "body"),
        ("title", "hey", "title"),
        ("source", "reddit", "source"),
        ("published_at", datetime.now(UTC).replace(tzinfo=None) + timedelta(30), "published_at"),
        ("symbols", ["DOGE"], "symbols"),
    ],
)
def test_contrato_rechaza_y_dice_el_campo(campo, valor, loc):
    datos = _valida() | {campo: valor}
    with pytest.raises(ValidationError) as exc:
        NewsItem(**datos)
    assert loc in {".".join(str(p) for p in e["loc"]) for e in exc.value.errors()}


def test_contrato_rechaza_campos_extra():
    with pytest.raises(ValidationError):
        NewsItem(**(_valida() | {"sentimiento": 0.9}))


def test_contrato_rechaza_id_inconsistente():
    with pytest.raises(ValidationError):
        NewsItem(**(_valida() | {"news_id": "0" * 32}))


# ───────────────────────────── silver ─────────────────────────────
def test_parse_extrae_los_items():
    regs = silver.parse_payload("coindesk", RSS)
    assert len(regs) == 3
    assert regs[0]["url"] == "https://example.com/nota-1"
    assert regs[0]["symbols"] == ["BTC"]


def test_cuarentena_registra_motivo(db):
    _sembrar("L1")
    res = silver.process_batch("L1")
    assert res["filas_validas"] == 2
    assert res["filas_rechazadas"] == 1
    con = get_connection()
    campo, msg = con.execute("SELECT error_field, error_msg FROM silver_rejects").fetchone()
    con.close()
    assert "url" in campo and "published_at" in campo and msg


def test_reproceso_del_mismo_lote_da_filas_nuevas_cero(db):
    _sembrar("L1")
    primera = silver.process_batch("L1")
    segunda = silver.process_batch("L1")
    tercera = silver.process_batch("L1")
    assert primera["filas_nuevas"] == 2
    assert segunda["filas_nuevas"] == 0
    assert tercera["filas_nuevas"] == 0
    assert segunda["total_silver"] == primera["total_silver"] == 2


def test_sin_duplicados_por_clave_natural(db):
    _sembrar("L1")
    _sembrar("L2")  # segundo lote con el MISMO contenido
    silver.process_batch("L1")
    silver.process_batch("L2")
    con = get_connection()
    dups = con.execute(
        "SELECT news_id FROM silver_news GROUP BY news_id HAVING count(*) > 1"
    ).fetchall()
    total = con.execute("SELECT count(*) FROM silver_news").fetchone()[0]
    con.close()
    assert dups == []
    assert total == 2


def test_cuarentena_no_duplica_al_reprocesar(db):
    _sembrar("L1")
    silver.process_batch("L1")
    silver.process_batch("L1")
    con = get_connection()
    n = con.execute("SELECT count(*) FROM silver_rejects").fetchone()[0]
    con.close()
    assert n == 1


# ───────────────────────────── gold ─────────────────────────────
def _embed_falso(textos: list[str]) -> np.ndarray:
    """Embedding determinista por hash — evita bajar el modelo en tests."""
    vecs = np.zeros((len(textos), gold.DIM), dtype="float32")
    for i, t in enumerate(textos):
        for palabra in t.lower().split():
            h = int(hashlib.md5(palabra.encode()).hexdigest(), 16)  # noqa: S324
            vecs[i, h % gold.DIM] += 1.0
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.where(norms == 0, 1, norms)


def test_indice_vectorial_y_busqueda(db, monkeypatch):
    monkeypatch.setattr(gold, "embed", _embed_falso)
    _sembrar("L1")
    silver.process_batch("L1")

    primera = gold.build_index()
    assert primera["vectores_nuevos"] == 2 and primera["index_ntotal"] == 2

    segunda = gold.build_index()  # idempotente: no re-embebe nada
    assert segunda["vectores_nuevos"] == 0 and segunda["index_ntotal"] == 2

    hits = gold.search("ethereum network upgrade staking", k=2)
    assert hits and "Ethereum" in hits[0]["title"]
    assert hits[0]["score"] >= hits[-1]["score"]
