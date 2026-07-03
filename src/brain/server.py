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
def run_daily() -> dict[str, Any]:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="corrida en curso — no se duplica")
    try:
        from scripts.daily_run import main as daily_main
        from src.brain.state_sync import download_state, upload_state

        db_path = download_state()
        rc = daily_main()
        upload_state()

        # rc=2 = freno de budget (la línea pre-autorizada se agotó): NO es un
        # error de infraestructura — 200 para que el Scheduler no reintente.
        return {"rc": rc, "db": db_path, "budget_blocked": rc == 2}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc
    finally:
        _run_lock.release()
