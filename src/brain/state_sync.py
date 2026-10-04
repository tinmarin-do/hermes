"""Sync del estado operacional con GCS (política de datos PRD §6).

El brain en Cloud Run es efímero: baja el DuckDB operacional del bucket de
estado al arrancar la corrida y lo sube al terminar (1 corrida/día = sin
concurrencia; el bucket tiene versioning para rollback). El histórico completo
de research vive en LOCAL y jamás depende de este archivo.
"""

import os
from pathlib import Path
from typing import Any

SNAPSHOT_LOCAL = Path(__file__).parent.parent / "dashboard" / "static" / "data" / "snapshot.json"
_DEFAULT_DB = "/tmp/hermes.duckdb"  # noqa: S108 — path efímero del contenedor Cloud Run


def _bucket() -> Any:
    from google.cloud import storage

    name = os.environ.get("HERMES_STATE_BUCKET", "")
    if not name:
        raise RuntimeError("HERMES_STATE_BUCKET no definido — el sync GCS es cloud-only")
    return storage.Client().bucket(name)


def download_state() -> str:
    """Baja gs://<bucket>/hermes.duckdb al HERMES_DUCKDB_PATH local (efímero)."""
    db_path = os.environ.get("HERMES_DUCKDB_PATH", _DEFAULT_DB)
    blob = _bucket().blob("hermes.duckdb")
    if not blob.exists():
        raise RuntimeError(
            "gs://.../hermes.duckdb no existe — sembrar el estado primero "
            "(gcloud storage cp data/hermes.duckdb gs://<state-bucket>/)"
        )
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(db_path)
    return db_path


def upload_state() -> None:
    """Sube el DuckDB operacional y el snapshot del dashboard al bucket."""
    db_path = os.environ.get("HERMES_DUCKDB_PATH", _DEFAULT_DB)
    bucket = _bucket()
    bucket.blob("hermes.duckdb").upload_from_filename(db_path)
    if SNAPSHOT_LOCAL.exists():
        blob = bucket.blob("snapshot.json")
        blob.cache_control = "no-cache"
        blob.upload_from_filename(str(SNAPSHOT_LOCAL), content_type="application/json")


# ── Bitácora durable de fills ────────────────────────────────────────────────
# El DuckDB operacional vive en /tmp y solo llega al bucket cuando la corrida
# TERMINA. Un fill es irreversible en el instante en que el venue lo acepta,
# así que toda la ventana entre ejecutar y subir es una zona donde el dinero
# ya se movió y el registro todavía no existe. Si la corrida muere ahí, el
# fill es real en Bitso y desaparece del ledger para siempre.
#
# Eso ya pasó: la forensia del 2026-10-03 encontró ~$375 de ventas ejecutadas
# que el ledger no tiene (caja +$514 contra lo que explican las órdenes, y
# posiciones reconstruidas $411 por encima del libro real).
#
# Un objeto por fill, escrito en el acto: sin read-modify-write, sin carrera,
# idempotente por order_id. Son bytes — el costo es ruido frente a perder la
# contabilidad de una orden real.


def journal_fill(record: dict[str, Any]) -> None:
    """Escribe UN fill a gs://<bucket>/fills/<fecha>/<order_id>.json, de inmediato.

    No-op sin bucket (modo local). **Nunca levanta**: que la bitácora falle no
    puede tumbar una ejecución en curso — pero grita en logs, porque un fill
    sin registrar es exactamente la deuda que esto viene a saldar.
    """
    if not os.environ.get("HERMES_STATE_BUCKET"):
        return
    try:
        import json

        oid = str(record["order_id"])
        day = str(record.get("filled_at", ""))[:10] or "sin-fecha"
        blob = _bucket().blob(f"fills/{day}/{oid}.json")
        blob.upload_from_string(json.dumps(record, default=str), content_type="application/json")
    except Exception as exc:  # noqa: BLE001 — degradar nunca debe romper la ejecución
        print(
            f'{{"severity":"ERROR","event":"FILL_JOURNAL_FAILED","order_id":'
            f'"{record.get("order_id")}","error":"{exc}"}}',
            flush=True,
        )


def recover_fills(con: Any) -> int:
    """Re-inserta los fills de la bitácora que falten en el DuckDB. → cuántos.

    Se corre al arrancar, después de bajar el estado: si la corrida anterior
    murió entre ejecutar y subir, sus fills viven solo en la bitácora y esta
    pasada los devuelve al ledger. Idempotente por ``order_id``.
    """
    if not os.environ.get("HERMES_STATE_BUCKET"):
        return 0
    import json

    recovered = 0
    try:
        known = {r[0] for r in con.execute("SELECT order_id FROM execution_orders").fetchall()}
        for blob in _bucket().list_blobs(prefix="fills/"):
            oid = blob.name.rsplit("/", 1)[-1].removesuffix(".json")
            if oid in known:
                continue
            rec = json.loads(blob.download_as_bytes())
            con.execute(
                """INSERT OR REPLACE INTO execution_orders
                   (order_id, run_id, symbol, action, quantity, price, status,
                    filled_at, created_at, cost_usd, fee_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    rec.get("order_id"),
                    rec.get("run_id"),
                    rec.get("symbol"),
                    rec.get("action"),
                    rec.get("quantity"),
                    rec.get("price"),
                    rec.get("status"),
                    rec.get("filled_at"),
                    rec.get("created_at") or rec.get("filled_at"),
                    rec.get("cost_usd"),
                    rec.get("fee_usd"),
                ],
            )
            recovered += 1
    except Exception as exc:  # noqa: BLE001 — la recuperación no puede bloquear la corrida
        print(f'{{"severity":"ERROR","event":"FILL_RECOVERY_FAILED","error":"{exc}"}}', flush=True)
    if recovered:
        print(
            f'{{"severity":"WARNING","event":"FILLS_RECOVERED","n":{recovered},'
            f'"note":"fills reales que el ledger había perdido"}}',
            flush=True,
        )
    return recovered
