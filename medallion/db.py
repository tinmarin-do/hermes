"""Conexión y esquema DuckDB del medallón.

Base separada de `hermes.duckdb` a propósito: este pipeline es un entregable
académico y no debe tocar las tablas del sistema en producción.
"""

import os
from pathlib import Path

import duckdb

DEFAULT_DB = "data/medallion.duckdb"
_ensured: set[str] = set()


def db_path() -> str:
    return os.environ.get("MEDALLION_DUCKDB_PATH", DEFAULT_DB)


def data_root() -> Path:
    """Raíz del almacén de archivos crudos (bronze) y artefactos (gold)."""
    return Path(os.environ.get("MEDALLION_DATA_DIR", "data/medallion"))


def get_connection() -> duckdb.DuckDBPyConnection:
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(path)
    if path not in _ensured:
        ensure_schema(con)
        _ensured.add(path)
    return con


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    # ── BRONZE: un renglón por (lote, fuente) con el payload tal cual llegó ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS bronze_batches (
            batch_id       VARCHAR   NOT NULL,
            source         VARCHAR   NOT NULL,
            feed_url       VARCHAR   NOT NULL,
            fetched_at     TIMESTAMP NOT NULL,
            http_status    INTEGER   NOT NULL,
            content_type   VARCHAR,
            payload_bytes  BIGINT    NOT NULL,
            payload_sha256 VARCHAR   NOT NULL,
            raw_path       VARCHAR   NOT NULL,
            raw_payload    VARCHAR   NOT NULL,
            PRIMARY KEY (batch_id, source)
        )
    """)

    # ── SILVER: tabla destino, clave natural = news_id ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver_news (
            news_id        VARCHAR   NOT NULL PRIMARY KEY,
            source         VARCHAR   NOT NULL,
            title          VARCHAR   NOT NULL,
            url            VARCHAR   NOT NULL,
            body           VARCHAR   NOT NULL,
            published_at   TIMESTAMP NOT NULL,
            symbols        VARCHAR   NOT NULL,
            content_hash   VARCHAR   NOT NULL,
            first_batch_id VARCHAR   NOT NULL,
            last_batch_id  VARCHAR   NOT NULL,
            inserted_at    TIMESTAMP NOT NULL,
            updated_at     TIMESTAMP NOT NULL
        )
    """)

    # ── CUARENTENA: registros que no pasaron el contrato, con motivo ──
    # PK (batch_id, source, record_ord) ⇒ reprocesar el mismo lote no duplica.
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver_rejects (
            batch_id      VARCHAR   NOT NULL,
            source        VARCHAR   NOT NULL,
            record_ord    INTEGER   NOT NULL,
            news_id       VARCHAR,
            error_field   VARCHAR   NOT NULL,
            error_type    VARCHAR   NOT NULL,
            error_msg     VARCHAR   NOT NULL,
            raw_record    VARCHAR   NOT NULL,
            quarantined_at TIMESTAMP NOT NULL,
            PRIMARY KEY (batch_id, source, record_ord)
        )
    """)

    # ── GOLD: mapa news_id → posición en el índice FAISS ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS gold_news_embeddings (
            news_id     VARCHAR   NOT NULL PRIMARY KEY,
            vec_ord     BIGINT    NOT NULL,
            model       VARCHAR   NOT NULL,
            dim         INTEGER   NOT NULL,
            embedded_at TIMESTAMP NOT NULL
        )
    """)

    # ── AUDITORÍA: evidencia de idempotencia, corrida por corrida ──
    con.execute("""
        CREATE TABLE IF NOT EXISTS load_audit (
            run_id            VARCHAR   NOT NULL,
            layer             VARCHAR   NOT NULL,
            batch_id          VARCHAR   NOT NULL,
            executed_at       TIMESTAMP NOT NULL,
            filas_leidas      BIGINT    NOT NULL,
            filas_validas     BIGINT    NOT NULL,
            filas_rechazadas  BIGINT    NOT NULL,
            filas_nuevas      BIGINT    NOT NULL,
            filas_actualizadas BIGINT   NOT NULL,
            PRIMARY KEY (run_id, layer, batch_id)
        )
    """)
