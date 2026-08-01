"""Orquestador y reporte de evidencia del medallón.

    python -m medallion run                 # E2E: nuevo lote → silver → gold → evidencia
    python -m medallion run --batch-id X    # reprocesa un lote existente (idempotencia)
    python -m medallion ingest              # sólo bronze
    python -m medallion evidence            # sólo las tablas de evidencia
    python -m medallion search "texto"      # búsqueda semántica
"""

import argparse
import sys
from datetime import UTC, datetime

from medallion import bronze, gold, silver
from medallion.db import db_path, get_connection


# ────────────────────────────── util de impresión ──────────────────────────────
def tabla(titulo: str, cols: list[str], filas: list[tuple]) -> None:
    print(f"\n{titulo}")
    if not filas:
        print("  (0 filas)")
        return
    datos = [[("" if c is None else str(c)) for c in f] for f in filas]
    anchos = [max(len(cols[i]), *(len(f[i]) for f in datos)) for i in range(len(cols))]
    linea = "  " + "  ".join("─" * a for a in anchos)
    print("  " + "  ".join(c.ljust(anchos[i]) for i, c in enumerate(cols)))
    print(linea)
    for f in datos:
        print("  " + "  ".join(f[i].ljust(anchos[i]) for i in range(len(cols))))


def _hoy() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


# ───────────────────────────────── evidencia ─────────────────────────────────
def evidencia(query_demo: str | None = None) -> dict:
    con = get_connection()
    print("=" * 78)
    print(f"EVIDENCIA — arquitectura medallón  ·  {_hoy()}  ·  db={db_path()}")
    print("=" * 78)

    # 1. BRONZE — lotes crudos con timestamp
    tabla(
        "1) BRONZE — lotes crudos almacenados sin transformar",
        ["batch_id", "fuentes", "fetched_at", "bytes_crudos", "sha256_distintos"],
        con.execute("""
            SELECT batch_id, count(*), min(fetched_at), sum(payload_bytes),
                   count(DISTINCT payload_sha256)
            FROM bronze_batches GROUP BY batch_id ORDER BY batch_id
        """).fetchall(),
    )
    n_lotes = con.execute("SELECT count(DISTINCT batch_id) FROM bronze_batches").fetchone()[0]

    # 2. CONTRATO — válidos vs cuarentena, con motivo
    tabla(
        "2) CONTRATO Pydantic — válidos vs cuarentena por lote",
        ["batch_id", "leídas", "válidas", "rechazadas"],
        con.execute("""
            SELECT batch_id, max(filas_leidas), max(filas_validas), max(filas_rechazadas)
            FROM load_audit GROUP BY batch_id ORDER BY batch_id
        """).fetchall(),
    )
    tabla(
        "   CUARENTENA — motivos de rechazo (silver_rejects)",
        ["campo", "tipo_error", "motivo", "n"],
        con.execute("""
            SELECT error_field, error_type, min(error_msg), count(*)
            FROM silver_rejects GROUP BY error_field, error_type
            ORDER BY count(*) DESC LIMIT 10
        """).fetchall(),
    )
    n_rej = con.execute("SELECT count(*) FROM silver_rejects").fetchone()[0]

    # 3. IDEMPOTENCIA — filas_nuevas por corrida
    filas_audit = con.execute("""
        SELECT run_id, batch_id, executed_at, filas_validas, filas_nuevas, filas_actualizadas
        FROM load_audit ORDER BY executed_at
    """).fetchall()
    tabla(
        "3) IDEMPOTENCIA — staging + MERGE por clave natural (news_id)",
        ["run_id", "batch_id", "executed_at", "válidas", "filas_nuevas", "filas_actualizadas"],
        filas_audit,
    )
    reprocesos = [f for f in filas_audit if f[4] == 0]

    # 4. DUPLICADOS — COUNT(*) > 1 por clave natural
    dups = con.execute("""
        SELECT news_id, count(*) FROM silver_news GROUP BY news_id HAVING count(*) > 1
    """).fetchall()
    tabla("4) DUPLICADOS — news_id con COUNT(*) > 1 (debe ser 0 filas)", ["news_id", "n"], dups)
    total_silver = con.execute("SELECT count(*) FROM silver_news").fetchone()[0]
    distintos = con.execute("SELECT count(DISTINCT news_id) FROM silver_news").fetchone()[0]
    print(f"   filas en silver_news = {total_silver}  ·  news_id distintos = {distintos}")

    # 5. GOLD — índice vectorial
    g = con.execute("""
        SELECT count(*), count(DISTINCT vec_ord), max(model), max(dim)
        FROM gold_news_embeddings
    """).fetchone()
    tabla(
        "5) GOLD — índice vectorial FAISS",
        ["vectores", "vec_ord_distintos", "modelo", "dim"],
        [g] if g[0] else [],
    )
    con.close()

    if g[0]:
        for q in [query_demo] if query_demo else DEMO_QUERIES:
            res = gold.search(q, k=3)
            tabla(
                f'   BÚSQUEDA SEMÁNTICA — "{q}"',
                ["score", "fuente", "título", "símbolos"],
                [(r["score"], r["source"], r["title"][:68], r["symbols"]) for r in res],
            )

    ok = {
        "bronze_2_lotes": n_lotes >= 2,
        "cuarentena_con_motivo": n_rej > 0,
        "reproceso_filas_nuevas_0": bool(reprocesos),
        "sin_duplicados": len(dups) == 0,
        "indice_vectorial": g[0] > 0,
    }
    print("\n" + "=" * 78)
    for k, v in ok.items():
        print(f"  [{'PASA' if v else 'FALLA'}] {k}")
    print("=" * 78)
    return ok


# Consultas en inglés porque el corpus (y el modelo MiniLM) lo son. Ninguna
# comparte palabras literales con los titulares que recupera: eso es lo que
# distingue la búsqueda SEMÁNTICA de un LIKE '%texto%'.
DEMO_QUERIES = [
    "lawsuit and regulatory crackdown by financial authorities",
    "institutional money flowing into spot ETFs",
    "sharp market selloff and price volatility",
]


# ─────────────────────────────────── comandos ───────────────────────────────────
def cmd_run(args: argparse.Namespace) -> int:
    batch_id = args.batch_id
    if batch_id:
        print(f"→ REPROCESO del lote existente {batch_id} (no se baja nada nuevo)")
    else:
        print("→ BRONZE: bajando lote crudo…")
        res = bronze.ingest_batch()
        batch_id = res["batch_id"]
        tabla(
            f"BRONZE lote {batch_id}",
            ["fuente", "http", "bytes", "sha256", "guardado"],
            [
                (r["source"], r["http_status"], r["bytes"], r["sha256"], r["stored"])
                for r in res["sources"]
            ],
        )

    print(f"\n→ SILVER: contrato + carga idempotente del lote {batch_id}…")
    s = silver.process_batch(batch_id)
    print(
        f"   leídas={s['filas_leidas']}  válidas={s['filas_validas']}  "
        f"rechazadas={s['filas_rechazadas']}  →  filas_nuevas={s['filas_nuevas']}  "
        f"actualizadas={s['filas_actualizadas']}  (total silver={s['total_silver']})"
    )

    print("\n→ GOLD: embeddings + índice FAISS…")
    g = gold.build_index(rebuild=args.rebuild_index)
    print(
        f"   modelo={g['modelo']}  dim={g['dim']}  nuevos={g['vectores_nuevos']}  "
        f"totales={g['vectores_totales']}  ntotal={g['index_ntotal']}"
    )

    ok = evidencia()
    return 0 if all(ok.values()) else 1


def cmd_ingest(args: argparse.Namespace) -> int:
    res = bronze.ingest_batch(sources=args.sources)
    tabla(
        f"BRONZE lote {res['batch_id']}",
        ["fuente", "http", "bytes", "sha256", "guardado"],
        [
            (r["source"], r["http_status"], r["bytes"], r["sha256"], r["stored"])
            for r in res["sources"]
        ],
    )
    return 0


def cmd_silver(args: argparse.Namespace) -> int:
    batch_id = args.batch_id or bronze.latest_batch_id()
    if not batch_id:
        print("no hay lotes en bronze; corré `ingest` primero", file=sys.stderr)
        return 1
    print(silver.process_batch(batch_id))
    return 0


def cmd_gold(args: argparse.Namespace) -> int:
    print(gold.build_index(rebuild=args.rebuild_index))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    res = gold.search(args.query, k=args.k)
    tabla(
        f'BÚSQUEDA SEMÁNTICA — "{args.query}"',
        ["score", "fuente", "título", "publicado", "símbolos"],
        [(r["score"], r["source"], r["title"][:70], r["published_at"], r["symbols"]) for r in res],
    )
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    ok = evidencia(args.query)
    return 0 if all(ok.values()) else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="medallion", description="Medallón bronze→silver→gold")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="pipeline completo de punta a punta")
    r.add_argument("--batch-id", help="reprocesar un lote existente en vez de bajar uno nuevo")
    r.add_argument("--rebuild-index", action="store_true")
    r.set_defaults(func=cmd_run)

    i = sub.add_parser("ingest", help="bronze: bajar un lote crudo")
    i.add_argument("--sources", nargs="*", default=None)
    i.set_defaults(func=cmd_ingest)

    s = sub.add_parser("silver", help="silver: contrato + carga idempotente")
    s.add_argument("--batch-id")
    s.set_defaults(func=cmd_silver)

    g = sub.add_parser("gold", help="gold: embeddings + índice FAISS")
    g.add_argument("--rebuild-index", action="store_true")
    g.set_defaults(func=cmd_gold)

    q = sub.add_parser("search", help="búsqueda semántica")
    q.add_argument("query")
    q.add_argument("-k", type=int, default=5)
    q.set_defaults(func=cmd_search)

    e = sub.add_parser("evidence", help="tablas de evidencia")
    e.add_argument("--query", default=None)
    e.set_defaults(func=cmd_evidence)

    args = p.parse_args(argv)
    return int(args.func(args))
