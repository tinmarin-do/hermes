"""Persistencia de transcripciones de corrida — visor de debate (PRD v0.3 §5.4/§10).

Cada corrida guarda un resumen auditable del camino de decisión: régimen, veredicto
del debate, aprobación de riesgo, decisión del PM y la transcripción (bull/bear,
rounds, síntesis de riesgo, señales y allocations). El dashboard lo lee del snapshot
($0 por visitante); `agents:debug` puede inspeccionarlo por `run_id`.
"""

import json
from datetime import UTC, datetime
from typing import Any

from src.data.db import get_connection


def _ensure_table(con: Any) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_transcripts (
            run_id            VARCHAR   NOT NULL,
            ts                TIMESTAMP NOT NULL,
            regime_summary    VARCHAR,
            debate_verdict    VARCHAR,
            debate_confidence DOUBLE,
            risk_approved     BOOLEAN,
            pm_action         VARCHAR,
            pm_rationale      VARCHAR,
            transcript_json   VARCHAR
        )
    """)


def persist_transcript(run_id: str, state: dict[str, Any]) -> None:
    """Guarda el resumen auditable de una corrida (una fila por run)."""
    pm = state.get("pm_decision", {}) or {}
    transcript = {
        "bull_argument": state.get("bull_argument", ""),
        "bear_argument": state.get("bear_argument", ""),
        "debate_rounds": state.get("debate_rounds", []),
        "risk_synthesis": state.get("risk_synthesis", ""),
        "quant_signals": state.get("quant_signals", []),
        "allocations": state.get("allocations", []),
        "pm_decision": pm,
    }
    con = get_connection()
    try:
        _ensure_table(con)
        con.execute(
            "INSERT INTO run_transcripts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                run_id,
                datetime.now(UTC).replace(tzinfo=None),
                state.get("regime_summary", ""),
                state.get("debate_verdict", ""),
                state.get("debate_confidence", 0.0),
                bool(state.get("risk_approved", False)),
                pm.get("action", ""),
                pm.get("rationale", ""),
                json.dumps(transcript, default=str),
            ],
        )
    finally:
        con.close()


def latest_transcript() -> dict[str, Any] | None:
    """Última corrida persistida (para el visor del dashboard). None si no hay."""
    con = get_connection()
    try:
        _ensure_table(con)
        row = con.execute(
            """SELECT run_id, ts, regime_summary, debate_verdict, debate_confidence,
                      risk_approved, pm_action, pm_rationale, transcript_json
               FROM run_transcripts ORDER BY ts DESC LIMIT 1"""
        ).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    return {
        "run_id": row[0],
        "ts": str(row[1]),
        "regime_summary": row[2],
        "debate_verdict": row[3],
        "debate_confidence": row[4],
        "risk_approved": bool(row[5]),
        "pm_action": row[6],
        "pm_rationale": row[7],
        "transcript": json.loads(row[8]) if row[8] else {},
    }
