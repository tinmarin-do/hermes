"""Brain HTTP server — Cloud Run (Fase 5). El Cloud Scheduler hace POST /run.

Flujo por invocación: bajar estado de GCS → corrida diaria completa (mismo
`scripts.daily_run` que el cron local: budget-guard → datos → noticias →
pipeline → dashboard snapshot) → subir estado + snapshot a GCS.

Un lock simple evita corridas concurrentes (el retry del Scheduler recibiría
409 mientras la primera sigue viva).
"""

import threading
from typing import Any

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Hermes Brain")
_run_lock = threading.Lock()


@app.get("/healthz")
@app.get("/health")  # /healthz es interceptado por el GFE en dominios run.app
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "hermes-brain"}


@app.post("/run")
def run_daily(force: bool = False, execute: bool = True) -> dict[str, Any]:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="corrida en curso — no se duplica")
    try:
        from scripts.daily_run import main as daily_main
        from src.brain.state_sync import download_state, recover_fills, upload_state

        db_path = download_state()

        # Si la corrida anterior murió entre ejecutar y subir, sus fills viven
        # solo en la bitácora durable. Devolverlos al ledger ANTES de decidir
        # nada: el allocator calcula el delta contra el libro, y un libro con
        # órdenes faltantes produce justo el churn fantasma del 23/24-ago.
        from src.data.db import get_connection

        con = get_connection()
        try:
            recover_fills(con)
        finally:
            con.close()

        rc = daily_main(force=force, execute=execute)

        # rc=2 (freno de budget) y rc=3 (ya corrió hoy) NO son errores de
        # infraestructura — 200 para que el Scheduler no reintente.
        return {
            "rc": rc,
            "db": db_path,
            "budget_blocked": rc == 2,
            "duplicate_blocked": rc == 3,
            "execute": execute,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc
    finally:
        # SIEMPRE, incluso si la corrida reventó: el DuckDB solo acumula, y una
        # corrida fallida pudo haber mandado órdenes reales antes de morir.
        # Antes el upload vivía en el camino feliz y una excepción borraba el
        # registro del día entero (fills reales incluidos).
        try:
            from src.brain.state_sync import upload_state

            upload_state()
        except Exception as exc:  # noqa: BLE001 — no enmascarar el error original
            print(
                f'{{"severity":"ERROR","event":"STATE_UPLOAD_FAILED","error":"{exc}"}}',
                flush=True,
            )
        _run_lock.release()
