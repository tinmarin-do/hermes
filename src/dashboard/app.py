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


_live_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_LIVE_TTL_S = 20


def _live_exchange() -> Any:
    """ccxt bitso con la key READ-ONLY (BITSO_RO_*) — jamás la key operativa.

    El servicio dashboard está expuesto (tras IAP); por eso usa una credencial
    de solo consulta (sin trading/retiro). None si no está configurada.
    """
    import os

    key = os.environ.get("BITSO_RO_KEY", "")
    secret = os.environ.get("BITSO_RO_SECRET", "")
    if not key or not secret:
        return None
    import ccxt

    return ccxt.bitso({"apiKey": key, "secret": secret, "enableRateLimit": True})


@app.get("/api/live")
def api_live() -> JSONResponse:
    """Cartera EN VIVO (informativo): balances read-only + tickers → equity al segundo.

    On-demand y con cache de 20s — $0 recurrente, solo corre cuando alguien mira.
    La curva OFICIAL de performance sigue siendo 1 punto/día (PRD §8.9): este
    endpoint no escribe nada, solo lee.
    """
    import time
    from datetime import UTC, datetime

    now = time.monotonic()
    if _live_cache["data"] is not None and now - _live_cache["ts"] < _LIVE_TTL_S:
        return JSONResponse(_live_cache["data"])

    ex = _live_exchange()
    if ex is None:
        raise HTTPException(status_code=503, detail="Sin credenciales read-only (BITSO_RO_*)")

    from src.execution.bitso import _BASE_ASSETS, _venue_pair

    try:
        bal = ex.fetch_balance()
        cash = sum(float((bal.get(c) or {}).get("total", 0) or 0) for c in ("USDT", "USD"))
        equity = cash
        positions: list[dict[str, Any]] = []
        for asset in _BASE_ASSETS:
            qty = float((bal.get(asset) or {}).get("total", 0) or 0)
            if qty <= 0:
                continue
            pair = _venue_pair(f"{asset}/USDT")
            last = float(ex.fetch_ticker(pair).get("last") or 0)
            value = qty * last
            equity += value
            positions.append(
                {
                    "symbol": f"{asset}/USDT",
                    "qty": qty,
                    "price": last,
                    "value_usd": round(value, 2),
                }
            )
        for p in positions:
            p["weight"] = round(p["value_usd"] / equity, 4) if equity else 0.0
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bitso no respondió: {exc}") from exc

    vs_snapshot: dict[str, Any] | None = None
    pf = (_load_snapshot() or {}).get("portfolio") or {}
    if pf.get("equity_usd"):
        then = float(pf["equity_usd"])
        vs_snapshot = {
            "at": (_load_snapshot() or {}).get("generated_at"),
            "equity_then": round(then, 2),
            "delta_usd": round(equity - then, 2),
            "delta_pct": round((equity - then) / then, 6) if then else 0.0,
        }

    data = {
        "available": True,
        "as_of": datetime.now(UTC).isoformat(),
        "equity_usd": round(equity, 2),
        "cash_usd": round(cash, 2),
        "positions": positions,
        "vs_snapshot": vs_snapshot,
        "note": "informativo — la curva oficial de performance es 1 punto/día (§8.9)",
    }
    _live_cache.update(ts=now, data=data)
    return JSONResponse(data)


def _claim_rerun_marker() -> bool:
    """True si ganamos el cupo de re-run del día (marker GCS creado atómicamente)."""
    import os
    from datetime import UTC, datetime

    bucket_name = os.environ.get("HERMES_STATE_BUCKET", "")
    if not bucket_name:
        return False
    from google.api_core.exceptions import PreconditionFailed
    from google.cloud import storage

    blob_name = f"watchdog/rerun-{datetime.now(UTC):%Y-%m-%d}.marker"
    blob = storage.Client().bucket(bucket_name).blob(blob_name)
    try:
        # if_generation_match=0 = "solo si NO existe" → atómico, sin carrera
        blob.upload_from_string(datetime.now(UTC).isoformat(), if_generation_match=0)
        return True
    except PreconditionFailed:
        return False  # cooldown: ya hubo re-run automático hoy (UTC)


def _release_rerun_marker() -> None:
    """Devuelve el cupo del día (best-effort) si el disparo del re-run falló."""
    import os
    from datetime import UTC, datetime

    bucket_name = os.environ.get("HERMES_STATE_BUCKET", "")
    if not bucket_name:
        return
    try:
        from google.cloud import storage

        blob_name = f"watchdog/rerun-{datetime.now(UTC):%Y-%m-%d}.marker"
        storage.Client().bucket(bucket_name).blob(blob_name).delete()
    except Exception:  # noqa: S110 — best-effort; el peor caso es un cupo quemado
        pass


def _run_emergency_job() -> None:
    """Dispara el job PAUSADO hermes-emergency-run: resume → run → pause.

    jobs.run devuelve 400 sobre un job pausado (cicatriz 2026-07-03, redescubierta
    en el drill) y el validador de cron rechaza fechas imposibles — así que el job
    vive pausado y se despierta ~1s para el disparo. El job (Scheduler) es quien
    alcanza al brain INTERNAL_ONLY con force=true; retry_count=0 = sin duplicados.
    """
    import os

    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    job = os.environ["HERMES_EMERGENCY_JOB"]
    creds, _ = google.auth.default()
    session = AuthorizedSession(creds)  # type: ignore[no-untyped-call]
    base = f"https://cloudscheduler.googleapis.com/v1/{job}"
    session.post(f"{base}:resume", json={}).raise_for_status()
    try:
        resp = session.post(f"{base}:run", json={})
        resp.raise_for_status()
    finally:
        # SIEMPRE re-pausar: si queda activo, el cron anual placeholder existiría
        try:
            session.post(f"{base}:pause", json={}).raise_for_status()
        except Exception as exc:  # noqa: S110 — best-effort; el run ya se despachó
            print(f"[watchdog] re-pause falló (job queda activo, revisar): {exc}")


@app.post("/api/check-drawdown")
def api_check_drawdown() -> JSONResponse:
    """Watchdog intradía (cada 30 min vía Scheduler): equity vivo vs snapshot oficial.

    Breach (delta ≤ −HERMES_DRAWDOWN_ALERT_PCT) → log DRAWDOWN_BREACH (la alert
    policy lo convierte en email) + re-run del comité, máx 1/día UTC (marker GCS).
    Siempre 200: un reintento del Scheduler no aporta nada aquí.
    """
    import os

    threshold = float(os.environ.get("HERMES_DRAWDOWN_ALERT_PCT", "0.03"))
    try:
        live: dict[str, Any] = json.loads(bytes(api_live().body))
    except HTTPException as exc:
        # Bitso caído / sin creds RO: no es breach — no alarmar por infraestructura
        return JSONResponse({"breach": False, "error": str(exc.detail), "threshold": threshold})

    delta = (live.get("vs_snapshot") or {}).get("delta_pct")
    breach = delta is not None and delta <= -threshold
    rerun = "not-applicable"
    if breach:
        # UNA línea JSON → Cloud Run la parsea a jsonPayload con severity=ERROR;
        # el filtro condition_matched_log de la alerta engancha event=DRAWDOWN_BREACH.
        print(
            json.dumps(
                {
                    "severity": "ERROR",
                    "event": "DRAWDOWN_BREACH",
                    "delta_pct": delta,
                    "equity_usd": live.get("equity_usd"),
                    "equity_then": (live.get("vs_snapshot") or {}).get("equity_then"),
                    "threshold": threshold,
                }
            ),
            flush=True,
        )
        if not os.environ.get("HERMES_EMERGENCY_JOB"):
            rerun = "disabled"
        elif not _claim_rerun_marker():
            rerun = "cooldown"
        else:
            try:
                _run_emergency_job()
                rerun = "triggered"
            except Exception as exc:
                _release_rerun_marker()
                rerun = f"error: {exc}"[:200]
    return JSONResponse(
        {"breach": breach, "delta_pct": delta, "threshold": threshold, "rerun": rerun}
    )


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
