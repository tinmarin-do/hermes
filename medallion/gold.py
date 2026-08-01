"""GOLD — embeddings + índice vectorial FAISS + búsqueda semántica.

Embeddings: `sentence-transformers/all-MiniLM-L6-v2` (384-d, CPU, local) sobre
el campo relevante = `title. body`. Índice: `IndexFlatIP` sobre vectores
L2-normalizados ⇒ el producto interno ES la similitud coseno.

La construcción es incremental e idempotente: sólo se embeben los `news_id`
que aún no están en `gold_news_embeddings`; su posición en el índice queda
registrada en `vec_ord`.
"""

import os
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import faiss
import numpy as np

from medallion.db import data_root, get_connection

MODEL_NAME = os.environ.get("MEDALLION_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DIM = 384


def index_path() -> str:
    p = data_root() / "gold"
    p.mkdir(parents=True, exist_ok=True)
    return str(p / "news.faiss")


@lru_cache(maxsize=1)
def _model() -> Any:
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed(textos: list[str]) -> np.ndarray:
    vecs = _model().encode(textos, batch_size=32, show_progress_bar=False)
    vecs = np.asarray(vecs, dtype="float32")
    faiss.normalize_L2(vecs)  # coseno vía producto interno
    return vecs


def _load_index() -> Any:
    ruta = index_path()
    if os.path.exists(ruta):
        return faiss.read_index(ruta)
    return faiss.IndexFlatIP(DIM)


def build_index(rebuild: bool = False) -> dict:
    """Embebe lo que falte y lo agrega al índice. Idempotente."""
    con = get_connection()
    if rebuild:
        con.execute("DELETE FROM gold_news_embeddings")
        if os.path.exists(index_path()):
            os.remove(index_path())

    idx = _load_index()
    n_previos = con.execute("SELECT count(*) FROM gold_news_embeddings").fetchone()[0]

    # el índice y la tabla deben ir en sincronía; si no, se reconstruye todo
    if idx.ntotal != n_previos:
        con.execute("DELETE FROM gold_news_embeddings")
        idx = faiss.IndexFlatIP(DIM)
        n_previos = 0

    pendientes = con.execute("""
        SELECT s.news_id, s.title, s.body
        FROM silver_news s
        LEFT JOIN gold_news_embeddings g USING (news_id)
        WHERE g.news_id IS NULL
        ORDER BY s.published_at
    """).fetchall()

    if pendientes:
        textos = [f"{t}. {b}"[:2000] for _, t, b in pendientes]
        vecs = embed(textos)
        base = idx.ntotal
        idx.add(vecs)
        ahora = datetime.now(UTC).replace(tzinfo=None)
        for i, (news_id, _, _) in enumerate(pendientes):
            con.execute(
                """INSERT INTO gold_news_embeddings (news_id, vec_ord, model, dim, embedded_at)
                   VALUES (?, ?, ?, ?, ?) ON CONFLICT (news_id) DO NOTHING""",
                [news_id, base + i, MODEL_NAME, DIM, ahora],
            )
        faiss.write_index(idx, index_path())

    total = con.execute("SELECT count(*) FROM gold_news_embeddings").fetchone()[0]
    con.close()
    return {
        "modelo": MODEL_NAME,
        "dim": DIM,
        "vectores_previos": n_previos,
        "vectores_nuevos": len(pendientes),
        "vectores_totales": total,
        "index_ntotal": idx.ntotal,
        "index_path": index_path(),
    }


def search(query: str, k: int = 5) -> list[dict]:
    """Búsqueda semántica: devuelve las k notas más cercanas al texto libre."""
    idx = _load_index()
    if idx.ntotal == 0:
        return []
    qv = embed([query])
    scores, ords = idx.search(qv, min(k, idx.ntotal))

    con = get_connection()
    out: list[dict] = []
    for score, vec_ord in zip(scores[0], ords[0], strict=True):
        if vec_ord < 0:
            continue
        row = con.execute(
            """SELECT s.news_id, s.source, s.title, s.url, s.published_at, s.symbols
               FROM gold_news_embeddings g JOIN silver_news s USING (news_id)
               WHERE g.vec_ord = ?""",
            [int(vec_ord)],
        ).fetchone()
        if row:
            out.append(
                {
                    "score": round(float(score), 4),
                    "news_id": row[0],
                    "source": row[1],
                    "title": row[2],
                    "url": row[3],
                    "published_at": row[4],
                    "symbols": row[5],
                }
            )
    con.close()
    return out
