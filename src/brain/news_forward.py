"""H10.4 — Logging forward de noticias (pre-registro DESIGN_H10 §H10.4).

Las noticias PASADAS quedaron descartadas DEFINITIVAMENTE como inferencia
(ratificación de Erika 2026-07-07): sin archivo histórico no hay backtest honesto.
El eje vive SOLO hacia adelante: cada corrida diaria persiste el vector de
features de noticias por símbolo y lo puntúa después contra retornos realizados.

Vector por símbolo (ventana = últimas 24h de titulares, fijada aquí ANTES de
acumular datos — es parte del protocolo):
- n_headlines: titulares limpios (injection_flag=FALSE) que mencionan el símbolo.
- novelty_frac: % de esos titulares SIN cluster (ruido HDBSCAN o aún sin clusterizar)
  — proxy de "historia nueva que la taxonomía no reconoce".
- sentiment_tw: sentimiento ponderado por trust sobre los clusterizados no-ruido
  (mapa direccional de gold/aggregate: bullish +0.6, bearish −0.4, resto 0).
- clusters_json: activación de clusters F4.0 ({label: count}).

Scoring (self-healing): en cada corrida, ANTES de insertar el vector de hoy, se
rellenan ret_24h/ret_7d de las filas pendientes cuyo horizonte ya cerró en
bronze_ohlcv. **Gates pre-registrados:** ninguna claim antes de n ≥ 90 días de
señales; al llegar, IC>0 p<0.05 en ≥1 horizonte habilita pre-registrar un
experimento direccional formal (con su propio DSR). Hasta entonces: solo acumula.
$0 — sin LLM, sin red; puro DuckDB local.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

WINDOW_H = 24  # ventana de titulares por corrida (protocolo, fijo)
GATE_DAYS = 90  # pre-registro: ninguna claim antes de esto
HORIZONS_H = {"ret_24h": 24, "ret_7d": 168}

# Mapa direccional del data layer (gold/aggregate) — importarlo crearía un ciclo
# potencial brain→data→brain; se fija aquí con la misma tabla.
BULLISH = {"protocol_upgrade", "listing", "adoption", "partnership"}
BEARISH = {"regulatory", "hack"}


def _sentiment(label: str) -> float:
    if label in BULLISH:
        return 0.6
    if label in BEARISH:
        return -0.4
    return 0.0


def _ensure_table(con: Any) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS news_forward_log (
            run_id        VARCHAR   NOT NULL,
            symbol        VARCHAR   NOT NULL,
            as_of         TIMESTAMP NOT NULL,
            n_headlines   INTEGER   NOT NULL,
            novelty_frac  DOUBLE,
            sentiment_tw  DOUBLE,
            clusters_json VARCHAR,
            ret_24h       DOUBLE,
            ret_7d        DOUBLE,
            scored_at     TIMESTAMP,
            created_at    TIMESTAMP NOT NULL,
            PRIMARY KEY (run_id, symbol)
        )
    """)


def build_news_vector(con: Any, symbol: str, as_of: datetime) -> dict[str, Any]:
    """Vector de features de noticias para UN símbolo en la ventana [as_of−24h, as_of]."""
    base = symbol.split("/")[0].upper()
    since = as_of - timedelta(hours=WINDOW_H)
    rows = con.execute(
        """
        SELECT snc.cluster_label, snc.is_noise, snc.trust_score
        FROM bronze_news bn
        LEFT JOIN silver_news_clusters snc
               ON snc.id = bn.id AND snc.source = bn.source
        WHERE bn.injection_flag = FALSE
          AND bn.published_at > ? AND bn.published_at <= ?
          AND bn.symbols LIKE '%"' || ? || '"%'
        """,
        [since, as_of, base],
    ).fetchall()

    n = len(rows)
    clustered = [(lbl, float(tr or 0.5)) for lbl, noise, tr in rows if lbl and not noise]
    novelty = round(1.0 - len(clustered) / n, 4) if n else None
    trust_sum = sum(tr for _, tr in clustered)
    sentiment_tw = (
        round(sum(_sentiment(lbl) * tr for lbl, tr in clustered) / trust_sum, 4)
        if trust_sum > 0
        else 0.0
    )
    activations: dict[str, int] = {}
    for lbl, _ in clustered:
        activations[lbl] = activations.get(lbl, 0) + 1

    return {
        "symbol": symbol,
        "n_headlines": n,
        "novelty_frac": novelty,
        "sentiment_tw": sentiment_tw,
        "clusters": activations,
    }


def _close_asof(con: Any, symbol: str, ts: datetime) -> float | None:
    row = con.execute(
        "SELECT close FROM bronze_ohlcv WHERE symbol=? AND timeframe='1h' AND ts <= ? "
        "ORDER BY ts DESC LIMIT 1",
        [symbol, ts],
    ).fetchone()
    return float(row[0]) if row else None


def score_pending(con: Any, now: datetime) -> int:
    """Rellena ret_24h/ret_7d de filas cuyo horizonte ya cerró. → filas actualizadas.

    Un horizonte se puntúa solo si bronze tiene datos HASTA as_of+H (nada parcial).
    """
    max_ts: dict[str, datetime] = {
        r[0]: r[1]
        for r in con.execute(
            "SELECT symbol, MAX(ts) FROM bronze_ohlcv WHERE timeframe='1h' GROUP BY symbol"
        ).fetchall()
    }
    pending = con.execute(
        "SELECT run_id, symbol, as_of, ret_24h, ret_7d FROM news_forward_log "
        "WHERE ret_24h IS NULL OR ret_7d IS NULL"
    ).fetchall()

    updated = 0
    for run_id, symbol, as_of, ret24, ret7 in pending:
        newvals = {"ret_24h": ret24, "ret_7d": ret7}
        changed = False
        for col, hours in HORIZONS_H.items():
            if newvals[col] is not None:
                continue
            target = as_of + timedelta(hours=hours)
            if symbol not in max_ts or max_ts[symbol] < target:
                continue  # horizonte aún abierto — se puntúa en una corrida futura
            p0 = _close_asof(con, symbol, as_of)
            p1 = _close_asof(con, symbol, target)
            if p0 and p1 and p0 > 0:
                newvals[col] = round(p1 / p0 - 1.0, 6)
                changed = True
        if changed:
            fully = newvals["ret_24h"] is not None and newvals["ret_7d"] is not None
            con.execute(
                "UPDATE news_forward_log SET ret_24h=?, ret_7d=?, scored_at=? "
                "WHERE run_id=? AND symbol=?",
                [newvals["ret_24h"], newvals["ret_7d"], now if fully else None, run_id, symbol],
            )
            updated += 1
    return updated


def log_news_forward(run_id: str, symbols: list[str]) -> dict[str, int]:
    """Puntúa lo pendiente + persiste el vector de hoy. → {"logged", "scored"}.

    Idempotente por (run_id, symbol). Nunca debe tumbar la corrida: el caller
    (runner) lo envuelve en try/except.
    """
    from src.data.db import get_connection

    now = datetime.now(UTC).replace(tzinfo=None)  # naive-UTC, como todo el stack
    con = get_connection()
    try:
        _ensure_table(con)
        scored = score_pending(con, now)
        logged = 0
        for symbol in symbols:
            vec = build_news_vector(con, symbol, now)
            con.execute(
                "INSERT OR REPLACE INTO news_forward_log "
                "(run_id, symbol, as_of, n_headlines, novelty_frac, sentiment_tw, "
                " clusters_json, ret_24h, ret_7d, scored_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?)",
                [
                    run_id,
                    symbol,
                    now,
                    vec["n_headlines"],
                    vec["novelty_frac"],
                    vec["sentiment_tw"],
                    json.dumps(vec["clusters"], sort_keys=True),
                    now,
                ],
            )
            logged += 1
    finally:
        con.close()
    return {"logged": logged, "scored": scored}


def forward_status() -> dict[str, Any]:
    """Progreso del protocolo hacia el gate de 90 días (para dashboard/reportes)."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        _ensure_table(con)
        n_days, n_rows, n_scored_24h, n_scored_7d = con.execute(
            "SELECT COUNT(DISTINCT CAST(as_of AS DATE)), COUNT(*), "
            "COUNT(ret_24h), COUNT(ret_7d) FROM news_forward_log"
        ).fetchone()
        latest = con.execute(
            "SELECT symbol, n_headlines, novelty_frac, sentiment_tw FROM news_forward_log "
            "WHERE as_of = (SELECT MAX(as_of) FROM news_forward_log) ORDER BY symbol"
        ).fetchall()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    finally:
        con.close()

    return {
        "available": True,
        "n_days": int(n_days),
        "gate_days": GATE_DAYS,
        "gate_reached": int(n_days) >= GATE_DAYS,
        "n_rows": int(n_rows),
        "n_scored_24h": int(n_scored_24h),
        "n_scored_7d": int(n_scored_7d),
        "latest": [
            {
                "symbol": r[0],
                "n_headlines": int(r[1]),
                "novelty_frac": r[2],
                "sentiment_tw": r[3],
            }
            for r in latest
        ],
        "note": (
            f"protocolo forward H10.4 — ninguna claim antes de {GATE_DAYS} días de "
            "señales; noticias pasadas descartadas como inferencia (2026-07-07)"
        ),
    }
