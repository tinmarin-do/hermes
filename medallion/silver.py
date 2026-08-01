"""SILVER — parseo, contrato Pydantic, cuarentena y carga idempotente.

Flujo de un lote:
    bronze_batches (crudo) → parse → validate(NewsItem)
        ├─ válidos   → staging `stg_news` → MERGE/UPSERT por clave natural
        └─ inválidos → `silver_rejects` (campo + tipo + motivo)

La carga es idempotente por construcción: la clave natural es
`news_id = sha256(source|url)` y el UPSERT sólo toca `updated_at` cuando el
`content_hash` cambió. Reprocesar el mismo lote ⇒ `filas_nuevas = 0`.
"""

import html
import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree  # noqa: S405  — feeds RSS de fuentes configuradas

from pydantic import ValidationError

from medallion.contracts import NewsItem, infer_symbols, natural_key
from medallion.db import get_connection

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _plain(text: str | None) -> str:
    """Quita tags/entidades HTML y colapsa espacios (limpieza propia de Silver)."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text))).strip()


def _parse_fecha(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    for parser in (parsedate_to_datetime, datetime.fromisoformat):
        try:
            dt = parser(raw)
            return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt
        except (TypeError, ValueError):
            continue
    return None


def _texto(el: Any) -> str | None:
    return el.text if el is not None else None


def parse_payload(source: str, payload: str) -> list[dict]:
    """Convierte el XML crudo en registros candidatos (aún SIN validar)."""
    try:
        root = ElementTree.fromstring(payload)  # noqa: S314
    except ElementTree.ParseError:
        return []

    items = root.findall(".//item") or root.findall(".//atom:entry", NS)
    out: list[dict] = []
    for it in items:
        titulo = _texto(it.find("title")) or _texto(it.find("atom:title", NS))
        link_el = it.find("link")
        url = _texto(link_el)
        if not url and link_el is not None:
            url = link_el.get("href")
        if not url:
            atom_link = it.find("atom:link", NS)
            url = atom_link.get("href") if atom_link is not None else None
        cuerpo = (
            _texto(it.find("description"))
            or _texto(it.find("content:encoded", NS))
            or _texto(it.find("atom:summary", NS))
            or _texto(it.find("atom:content", NS))
        )
        fecha = (
            _texto(it.find("pubDate"))
            or _texto(it.find("atom:published", NS))
            or _texto(it.find("atom:updated", NS))
            or _texto(it.find("dc:date", NS))
        )
        titulo, cuerpo, url = _plain(titulo), _plain(cuerpo), (url or "").strip()
        out.append(
            {
                "news_id": natural_key(source, url) if url else None,
                "source": source,
                "title": titulo,
                "url": url,
                "body": cuerpo,
                "published_at": _parse_fecha(fecha),
                "symbols": infer_symbols(f"{titulo} {cuerpo}"),
            }
        )
    return out


def _motivo(exc: ValidationError) -> tuple[str, str, str]:
    """Errores del contrato → (campos, tipo, mensaje) para la cuarentena.

    `news_id` es derivado de la URL: si falla junto con otro campo, el motivo
    que importa es el otro (la causa raíz, no la consecuencia).
    """
    errs = exc.errors()
    campos = [".".join(str(p) for p in e.get("loc", ())) or "<registro>" for e in errs]
    raiz = next((e for e, c in zip(errs, campos, strict=True) if c != "news_id"), errs[0])
    return (
        ",".join(dict.fromkeys(campos)),
        raiz.get("type", "value_error"),
        str(raiz.get("msg", "inválido")),
    )


def process_batch(batch_id: str, run_id: str | None = None) -> dict:
    """Valida + carga un lote de Bronze a Silver. Idempotente por clave natural."""
    run_id = run_id or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    con = get_connection()
    crudos = con.execute(
        "SELECT source, raw_payload FROM bronze_batches WHERE batch_id = ? ORDER BY source",
        [batch_id],
    ).fetchall()
    if not crudos:
        con.close()
        raise ValueError(f"lote inexistente en bronze: {batch_id}")

    validos: list[NewsItem] = []
    rechazos: list[list] = []
    leidos = 0
    ahora = datetime.now(UTC).replace(tzinfo=None)

    for source, payload in crudos:
        for ord_, raw in enumerate(parse_payload(source, payload)):
            leidos += 1
            try:
                validos.append(NewsItem(**raw))
            except ValidationError as exc:
                campo, tipo, msg = _motivo(exc)
                rechazos.append(
                    [
                        batch_id,
                        source,
                        ord_,
                        raw.get("news_id"),
                        campo,
                        tipo,
                        msg,
                        json.dumps(raw, default=str)[:4000],
                        ahora,
                    ]
                )

    # ── cuarentena (idempotente: PK batch_id+source+record_ord) ──
    for r in rechazos:
        con.execute(
            """INSERT INTO silver_rejects
                 (batch_id, source, record_ord, news_id, error_field, error_type,
                  error_msg, raw_record, quarantined_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (batch_id, source, record_ord) DO NOTHING""",
            r,
        )

    # ── STAGING: se reconstruye en cada corrida, deduplicado por clave natural ──
    con.execute("""
        CREATE OR REPLACE TABLE stg_news (
            news_id VARCHAR, source VARCHAR, title VARCHAR, url VARCHAR, body VARCHAR,
            published_at TIMESTAMP, symbols VARCHAR, content_hash VARCHAR, batch_id VARCHAR
        )
    """)
    for it in validos:
        con.execute(
            "INSERT INTO stg_news VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                it.news_id,
                it.source,
                it.title,
                it.url,
                it.body,
                it.published_at,
                json.dumps(it.symbols),
                it.content_hash(),
                batch_id,
            ],
        )
    # el mismo feed puede repetir una nota dentro del lote: gana la más reciente
    con.execute("""
        CREATE OR REPLACE TABLE stg_news AS
        SELECT * FROM stg_news
        QUALIFY row_number() OVER (PARTITION BY news_id ORDER BY published_at DESC) = 1
    """)

    n_stg = con.execute("SELECT count(*) FROM stg_news").fetchone()[0]
    n_match = con.execute("""
        SELECT count(*) FROM stg_news s JOIN silver_news t USING (news_id)
    """).fetchone()[0]
    n_cambian = con.execute("""
        SELECT count(*) FROM stg_news s JOIN silver_news t USING (news_id)
        WHERE s.content_hash IS DISTINCT FROM t.content_hash
    """).fetchone()[0]
    filas_nuevas = n_stg - n_match

    # ── MERGE / UPSERT por clave natural ──
    con.execute(
        """
        INSERT INTO silver_news
            (news_id, source, title, url, body, published_at, symbols,
             content_hash, first_batch_id, last_batch_id, inserted_at, updated_at)
        SELECT news_id, source, title, url, body, published_at, symbols,
               content_hash, batch_id, batch_id, ?, ?
        FROM stg_news
        ON CONFLICT (news_id) DO UPDATE SET
            title         = excluded.title,
            url           = excluded.url,
            body          = excluded.body,
            published_at  = excluded.published_at,
            symbols       = excluded.symbols,
            content_hash  = excluded.content_hash,
            last_batch_id = excluded.last_batch_id,
            updated_at    = CASE
                                WHEN silver_news.content_hash IS DISTINCT FROM excluded.content_hash
                                THEN excluded.updated_at
                                ELSE silver_news.updated_at
                            END
        """,
        [ahora, ahora],
    )

    con.execute(
        """INSERT INTO load_audit
             (run_id, layer, batch_id, executed_at, filas_leidas, filas_validas,
              filas_rechazadas, filas_nuevas, filas_actualizadas)
           VALUES (?, 'silver', ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (run_id, layer, batch_id) DO NOTHING""",
        [run_id, batch_id, ahora, leidos, len(validos), len(rechazos), filas_nuevas, n_cambian],
    )
    total = con.execute("SELECT count(*) FROM silver_news").fetchone()[0]
    con.close()

    return {
        "run_id": run_id,
        "batch_id": batch_id,
        "filas_leidas": leidos,
        "filas_validas": len(validos),
        "filas_rechazadas": len(rechazos),
        "filas_staging": n_stg,
        "filas_nuevas": filas_nuevas,
        "filas_actualizadas": n_cambian,
        "total_silver": total,
    }
