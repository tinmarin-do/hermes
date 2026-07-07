"""Corrida diaria local — cron-safe, con freno de budget (PRD v0.3 §8.8).

Una corrida programada NO puede pasar por /cost:gate interactivo (regla #6); en su
lugar consume contra la LÍNEA PRE-AUTORIZADA del ledger (julio 2026: cap $0.50,
autorizada 2026-07-02). Este script verifica el consumo acumulado de corridas
diarias del mes ANTES de gastar y SE FRENA si la línea está agotada.

Pasos: budget-guard → bronze incremental → silver tail → news (ingest+cluster)
→ pipeline (LLM) → registrar consumo + mark_logged → dashboard snapshot.

Uso (cron):  .venv/bin/python -m scripts.daily_run   (ver scripts/daily_run.sh)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime

# Env explícito: los defaults del código ya son los correctos, pero el cron no
# hereda direnv → forzar lo crítico (lección 2026-06/07: env viejo colgado).
os.environ.setdefault("HERMES_MODE", "local")
os.environ.setdefault("EXCHANGE_MODE", "paper")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

DAILY_LINE_CAP_USD = float(os.environ.get("HERMES_DAILY_LINE_CAP_USD", "0.50"))
EST_RUN_COST_USD = 0.011  # medido ~$0.0105 → margen
TAIL_HOURS = int(os.environ.get("HERMES_DAILY_TAIL_HOURS", "48"))


def _symbols() -> list[str]:
    raw = os.environ.get(
        "HERMES_ALLOWED_SYMBOLS",
        "BTC/USDT,ETH/USDT,SOL/USDT,LINK/USDT,AVAX/USDT,XRP/USDT",
    )
    return [s.strip() for s in raw.split(",") if s.strip()]


def _ensure_log_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_run_log (
            run_id   VARCHAR   NOT NULL,
            ts       TIMESTAMP NOT NULL,
            cost_usd DOUBLE,
            status   VARCHAR
        )
    """)


def _month_daily_spend() -> float:
    """Consumo del mes corriente contra la línea pre-autorizada (solo corridas diarias)."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        _ensure_log_table(con)
        # Mes UTC EXPLÍCITO desde Python (revisión 2026-07-06): current_date usa la
        # tz LOCAL del host y los ts se guardan naive-UTC — en hosts no-UTC el
        # cruce de medianoche desalinea mes/día (el guard quedaba ciego 18-24h MX).
        month_start = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0, tzinfo=None
        )
        row = con.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM daily_run_log WHERE ts >= ?",
            [month_start],
        ).fetchone()
        return float(row[0]) if row else 0.0
    finally:
        con.close()


def _ran_ok_today() -> bool:
    """True si ya hay una corrida OK hoy — el Scheduler y un trigger manual no deben
    pisarse (2026-07-03: el solape ejecutó un BUY duplicado el mismo día)."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        _ensure_log_table(con)
        # Día UTC EXPLÍCITO (revisión 2026-07-06): comparar contra current_date
        # (tz local) dejaba el guard CIEGO cada noche 18-24h MX en hosts no-UTC
        # (los ts son naive-UTC). En cloud funcionaba solo porque el contenedor
        # corre en UTC — suposición implícita eliminada.
        row = con.execute(
            "SELECT count(*) FROM daily_run_log WHERE status = 'OK' AND CAST(ts AS DATE) = ?",
            [datetime.now(UTC).date()],
        ).fetchone()
        return bool(row and row[0] > 0)
    finally:
        con.close()


def _record_run(run_id: str, cost_usd: float, status: str) -> None:
    from src.data.db import get_connection

    con = get_connection()
    try:
        _ensure_log_table(con)
        con.execute(
            "INSERT INTO daily_run_log VALUES (?, ?, ?, ?)",
            [run_id, datetime.now(UTC).replace(tzinfo=None), cost_usd, status],
        )
    finally:
        con.close()


def main(force: bool = False) -> int:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(f"════ daily_run {stamp} ════", flush=True)
    symbols = _symbols()
    force = force or os.environ.get("HERMES_FORCE_RUN", "") == "1"

    # ── 0. Guard anti-duplicado: 1 corrida OK por día (salvo force explícito) ──
    if not force and _ran_ok_today():
        print(
            "⛔ DUPLICADO: ya hubo una corrida OK hoy — el Scheduler y los triggers "
            "manuales no se acumulan. Corrida manual intencional: HERMES_FORCE_RUN=1 "
            "o POST /run?force=true."
        )
        _record_run("(duplicate)", 0.0, "BLOCKED_DUPLICATE")
        return 3

    # ── 1. Freno de budget (regla #6 sin gate interactivo) ──
    spent = _month_daily_spend()
    if spent + EST_RUN_COST_USD > DAILY_LINE_CAP_USD:
        print(
            f"⛔ FRENO: línea diaria agotada (${spent:.4f} + est ${EST_RUN_COST_USD} "
            f"> cap ${DAILY_LINE_CAP_USD}). Re-autorizar vía /cost:gate para continuar."
        )
        _record_run("(skipped)", 0.0, "BLOCKED_BUDGET")
        return 2
    print(f"[budget] línea diaria: ${spent:.4f} / ${DAILY_LINE_CAP_USD} — OK", flush=True)

    # ── 2. Bronze incremental (ccxt, $0) ──
    from datetime import timedelta

    from src.data.bronze.ingest import ingest
    from src.data.db import get_connection

    now = datetime.now(UTC).replace(tzinfo=None)
    for sym in symbols:
        con = get_connection()
        last = con.execute(
            "SELECT max(ts) FROM bronze_ohlcv WHERE symbol=? AND timeframe='1h'", [sym]
        ).fetchone()[0]
        con.close()
        since = (last + timedelta(hours=1)) if last else now - timedelta(days=30)
        if since >= now:
            continue
        try:
            n = ingest(sym, "1h", since, now)
            print(f"[bronze] {sym}: +{n} velas", flush=True)
        except Exception as exc:
            print(f"[bronze] {sym}: ⚠️ {exc}", flush=True)

    # ── 3. Silver incremental (tail) ──
    from src.data.silver.transform import transform_tail

    for sym in symbols:
        try:
            n = transform_tail(sym, "1h", tail_hours=TAIL_HOURS)
            print(f"[silver] {sym}: {n} filas upserted", flush=True)
        except Exception as exc:
            print(f"[silver] {sym}: ⚠️ {exc}", flush=True)

    # ── 4. Noticias: ingest + clustering ($0 LLM) ──
    try:
        from src.data.bronze.news import ingest_news
        from src.data.silver.news_transform import transform_news

        ns = ingest_news(symbols, limit=50)
        print(f"[news] {ns['stored']} ingestadas · {ns['flagged']} flageadas", flush=True)
        ts_summary = transform_news()
        print(
            f"[news] clusters={ts_summary.get('n_clusters')} "
            f"noise={ts_summary.get('noise_frac')} "
            f"drift_alert={ts_summary.get('drift_alert')}",
            flush=True,
        )
    except Exception as exc:
        print(f"[news] ⚠️ {exc} — la corrida sigue sin noticias frescas", flush=True)

    # ── 5. Pipeline completo (LLM — consume la línea pre-autorizada) ──
    from src.brain.runner import run

    try:
        final_state = run(symbols=symbols, timeframe="1h")
    except Exception as exc:
        print(f"[pipeline] ❌ {exc}", flush=True)
        _record_run("(failed)", 0.0, f"FAILED: {exc}"[:200])
        return 1

    run_id = final_state.get("run_id", "?")
    cost = float(final_state.get("cost", {}).get("cost_usd", 0.0))

    # ── 6. Registrar consumo contra la línea + flag en cost_meter ──
    _record_run(run_id, cost, "OK")
    from src.brain.cost_meter import mark_logged

    mark_logged(run_id)  # consumido contra la línea PRE-AUTORIZACIÓN del ledger
    total = _month_daily_spend()
    print(f"[budget] corrida ${cost:.4f} → línea: ${total:.4f} / ${DAILY_LINE_CAP_USD}", flush=True)

    # ── 7. Dashboard snapshot (equity curve suma su punto diario) ──
    try:
        from src.dashboard.build import SNAPSHOT_PATH, build_snapshot

        snap = build_snapshot()
        SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2, default=str))
        pf = snap["portfolio"]
        print(
            f"[dashboard] equity ${pf.get('equity_usd')} · cash ${pf.get('balance_usd')} "
            f"· snapshot OK",
            flush=True,
        )
    except Exception as exc:
        print(f"[dashboard] ⚠️ {exc}", flush=True)

    print("════ daily_run DONE ════", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
