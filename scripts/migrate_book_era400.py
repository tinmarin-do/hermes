"""Migración del libro paper: era-$1 → era-$400 (decisión 2026-07-03, PRD §13).

Mismo patrón que la migración era-$500→$1 (2026-07-02): MEDIR el rendimiento del
ejercicio viejo → ARCHIVAR (tablas *_archive_* dentro del mismo DuckDB) → VACIAR
las tablas vivas. La equity curve también se archiva: el salto de escala $1→$400
rompería la serie; el track record de señales (shadow_signals) NO se toca — ese
es el juez del research (§8.9) y es scale-free.

Por default solo MIDE y reporta (dry-run). El wipe requiere `--yes` explícito.
`--cloud` opera contra el DuckDB del bucket de estado GCS (baja → migra → sube).

Uso:
    uv run python -m scripts.migrate_book_era400 [--cloud]        # solo reporte
    uv run python -m scripts.migrate_book_era400 [--cloud] --yes  # migra de verdad
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from typing import Any

ARCHIVE_SUFFIX = datetime.now(UTC).strftime("archive_%Y%m%d_era1")
# Identificadores FIJOS del módulo (jamás input externo) → los f-string SQL de abajo
# no son vector de inyección (noqa S608).
TABLES = ["execution_orders", "execution_positions", "equity_curve"]


def _report(con: Any) -> None:
    print("── Ejercicio era-$1 (medición pre-wipe) ──")
    for t in TABLES:
        try:
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: S608
        except Exception:
            n = "(no existe)"
        print(f"  {t}: {n} filas")
    try:
        row = con.execute(
            "SELECT COALESCE(SUM(cost_usd * CASE WHEN action='BUY' THEN -1 ELSE 1 END), 0), "
            "COALESCE(SUM(fee_usd), 0), count(*) FROM execution_orders"
        ).fetchone()
        print(f"  flujo neto de caja: ${row[0]:+.4f} · fees ${row[1]:.4f} · {row[2]} órdenes")
    except Exception as exc:
        print(f"  (sin métricas de órdenes: {exc})")
    try:
        pos = con.execute(
            "SELECT symbol, action, quantity, entry_price FROM execution_positions"
        ).fetchall()
        for p in pos:
            print(f"  posición abierta: {p[0]} {p[1]} qty={p[2]} @ {p[3]}")
    except Exception as exc:
        print(f"  (sin posiciones abiertas legibles: {exc})")


def _migrate(con: Any) -> None:
    for t in TABLES:
        try:
            con.execute(f"CREATE TABLE {t}_{ARCHIVE_SUFFIX} AS SELECT * FROM {t}")  # noqa: S608
            con.execute(f"DELETE FROM {t}")  # noqa: S608
            print(f"  ✓ {t} → {t}_{ARCHIVE_SUFFIX} (viva vaciada)")
        except Exception as exc:
            print(f"  ⚠️ {t}: {exc}")


def main() -> int:
    cloud = "--cloud" in sys.argv
    do_wipe = "--yes" in sys.argv

    if cloud:
        import tempfile

        from src.brain.state_sync import _bucket

        bucket = _bucket()
        blob = bucket.blob("hermes.duckdb")
        with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as tmp:
            tmp_path = tmp.name
        blob.download_to_filename(tmp_path)
        os.environ["HERMES_DUCKDB_PATH"] = tmp_path
        print(f"[cloud] estado bajado de gs://{bucket.name}/hermes.duckdb")

    from src.data.db import get_connection

    con = get_connection()
    try:
        _report(con)
        if not do_wipe:
            print("\n(dry-run — nada modificado; correr con --yes para migrar)")
            return 0
        print(f"\n── Migrando (archivo {ARCHIVE_SUFFIX}) ──")
        _migrate(con)
    finally:
        con.close()

    if cloud:
        # timeout amplio: ~120MB desde uplink doméstico excede el default de 120s
        bucket.blob("hermes.duckdb").upload_from_filename(tmp_path, timeout=600)
        os.unlink(tmp_path)
        print(f"[cloud] estado migrado subido a gs://{bucket.name}/hermes.duckdb")
    print("✅ era-$400 lista: libro en cash, equity curve fresca; shadow_signals intacto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
