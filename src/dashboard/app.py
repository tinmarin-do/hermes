"""Hermes dashboard — FastAPI + Jinja2 + Chart.js.

Serves a static snapshot (built by src.dashboard.build) so per-visitor cost is
$0. The SHAP panel explains the quant core's latest prediction per symbol.

Run locally:
    uv run uvicorn src.dashboard.app:app --reload --port 8080
"""
from __future__ import annotations

import json
from pathlib import Path

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


def _load_snapshot() -> dict | None:
    if not SNAPSHOT_PATH.exists():
        return None
    try:
        return json.loads(SNAPSHOT_PATH.read_text())
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
def healthz() -> dict:
    return {"status": "ok", "has_snapshot": SNAPSHOT_PATH.exists()}
