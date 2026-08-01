"""BRONZE — ingesta cruda de feeds públicos, sin autenticación.

Regla de la capa: el payload se guarda **tal cual llegó** (bytes → texto, sin
parsear, sin limpiar HTML, sin recortar). Un lote = una corrida de ingesta,
identificada por `batch_id` (timestamp UTC) y persistida por partida doble:
archivo en disco (`data/medallion/bronze/<batch_id>/<source>.xml`) y renglón en
`bronze_batches` con su SHA-256.
"""

import hashlib
from datetime import UTC, datetime

import httpx

from medallion.db import data_root, get_connection

# Feeds RSS públicos: ni API key ni token ni cuenta.
FEEDS: dict[str, str] = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
}

USER_AGENT = "hermes-medallion/1.0 (+diplomado; contacto via repo)"


def new_batch_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def ingest_batch(sources: list[str] | None = None, batch_id: str | None = None) -> dict:
    """Baja un lote crudo de cada fuente y lo persiste intacto.

    Devuelve: {batch_id, fetched_at, sources: [{source, http_status, bytes, sha256}]}
    """
    names = sources or list(FEEDS)
    batch_id = batch_id or new_batch_id()
    out_dir = data_root() / "bronze" / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)

    con = get_connection()
    rows = []
    for name in names:
        url = FEEDS[name]
        fetched_at = datetime.now(UTC).replace(tzinfo=None)
        try:
            resp = httpx.get(
                url,
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml,*/*"},
            )
            status = resp.status_code
            payload = resp.text
            ctype = resp.headers.get("content-type", "")
        except httpx.HTTPError as exc:  # la fuente caída no tumba el lote
            status, payload, ctype = 0, "", f"error: {type(exc).__name__}"

        if status != 200 or not payload:
            rows.append(
                {"source": name, "http_status": status, "bytes": 0, "sha256": "", "stored": False}
            )
            continue

        raw_path = out_dir / f"{name}.xml"
        raw_path.write_text(payload, encoding="utf-8")  # crudo, byte a byte
        sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        con.execute(
            """
            INSERT INTO bronze_batches
                (batch_id, source, feed_url, fetched_at, http_status, content_type,
                 payload_bytes, payload_sha256, raw_path, raw_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (batch_id, source) DO NOTHING
            """,
            [
                batch_id,
                name,
                url,
                fetched_at,
                status,
                ctype,
                len(payload.encode("utf-8")),
                sha,
                str(raw_path),
                payload,
            ],
        )
        rows.append(
            {
                "source": name,
                "http_status": status,
                "bytes": len(payload.encode("utf-8")),
                "sha256": sha[:12],
                "stored": True,
            }
        )

    con.close()
    return {"batch_id": batch_id, "sources": rows}


def list_batches() -> list[tuple]:
    con = get_connection()
    rows = con.execute("""
        SELECT batch_id,
               COUNT(*)              AS fuentes,
               MIN(fetched_at)       AS fetched_at,
               SUM(payload_bytes)    AS bytes_crudos,
               COUNT(DISTINCT payload_sha256) AS payloads_distintos
        FROM bronze_batches
        GROUP BY batch_id
        ORDER BY batch_id
    """).fetchall()
    con.close()
    return rows


def latest_batch_id() -> str | None:
    con = get_connection()
    row = con.execute("SELECT max(batch_id) FROM bronze_batches").fetchone()
    con.close()
    return row[0] if row and row[0] else None
