"""Hermes dashboard — FastAPI + Jinja2 + Chart.js.

Serves a static snapshot (built by src.dashboard.build) so per-visitor cost is
$0. The SHAP panel explains the quant core's latest prediction per symbol.

Run locally:
    uv run uvicorn src.dashboard.app:app --reload --port 8080
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
SNAPSHOT_PATH = STATIC_DIR / "data" / "snapshot.json"

app = FastAPI(title="Hermes Dashboard")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


_gcs_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_GCS_TTL_S = 60


def _load_snapshot() -> dict[str, Any] | None:
    # Cloud (Fase 5): el brain sube snapshot.json al bucket de estado tras cada
    # corrida; el dashboard lo lee de ahí con un cache corto ($0 por visitante).
    import os
    import time

    bucket_name = os.environ.get("HERMES_STATE_BUCKET", "")
    if bucket_name:
        now = time.monotonic()
        if _gcs_cache["data"] is not None and now - _gcs_cache["ts"] < _GCS_TTL_S:
            return _gcs_cache["data"]  # type: ignore[no-any-return]
        try:
            from google.cloud import storage

            blob = storage.Client().bucket(bucket_name).blob("snapshot.json")
            data: dict[str, Any] = json.loads(blob.download_as_text())
            _gcs_cache.update(ts=now, data=data)
            return data
        except Exception:
            return _gcs_cache["data"]  # type: ignore[no-any-return]

    if not SNAPSHOT_PATH.exists():
        return None
    try:
        local: dict[str, Any] = json.loads(SNAPSHOT_PATH.read_text())
        return local
    except (json.JSONDecodeError, OSError):
        return None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    snapshot = _load_snapshot()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"snapshot": snapshot, "has_snapshot": snapshot is not None},
    )


@app.get("/api/snapshot")
def api_snapshot() -> JSONResponse:
    snapshot = _load_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No snapshot — run dashboard:build first")
    return JSONResponse(snapshot)


@app.get("/api/explain/{base}")
def api_explain(base: str) -> JSONResponse:
    """Live SHAP explanation for one symbol (e.g. /api/explain/BTC).

    On-demand inference — small cost in compute, $0 LLM (quant core only).
    """
    import os

    from src.brain.quant_core import QuantCore
    from src.data.gold.aggregate import aggregate

    symbol = f"{base.upper()}/USDT" if "/" not in base else base.upper()
    try:
        core = QuantCore.load()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No model: {exc}") from exc
    if not core.is_trained():
        raise HTTPException(status_code=503, detail="Model not ready")

    timeframe = os.environ.get("HERMES_TIMEFRAME", "1h")
    signals = aggregate([symbol], timeframe)
    if not signals:
        raise HTTPException(status_code=404, detail=f"No signal for {symbol}")
    return JSONResponse({"symbol": symbol, "explanation": core.explain(signals[0])})


@app.get("/healthz")
@app.get("/health")  # /healthz es interceptado por el GFE en dominios run.app
def healthz() -> dict[str, Any]:
    return {"status": "ok", "has_snapshot": _load_snapshot() is not None}
