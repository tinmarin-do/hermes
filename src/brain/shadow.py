"""Signal log — persistencia de señales champion + challenger (PRD v0.3 §5.2/§8.9).

Tabla `shadow_signals`: una fila por (run, modelo, símbolo). El **champion**
(`model='champion-multimom'`) registra lo que la señal ejecutora dijo en cada
corrida; los **challengers** (LightGBM hoy, regresión mañana) registran señales
hipotéticas que JAMÁS ejecutan. El panel champion-vs-shadow del dashboard y el
protocolo de research §8.9 comparan ambos streams — datos del futuro real,
imposibles de overfittear — para decidir promociones.
"""

from datetime import UTC, datetime
from typing import Any

from src.data.db import get_connection


def _ensure_table(con: Any) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS shadow_signals (
            run_id          VARCHAR   NOT NULL,
            model           VARCHAR   NOT NULL,
            symbol          VARCHAR   NOT NULL,
            direction       VARCHAR   NOT NULL,
            confidence      DOUBLE,
            raw_probability DOUBLE,
            size_usd        DOUBLE,
            created_at      TIMESTAMP NOT NULL
        )
    """)


def persist_shadow_signals(run_id: str, shadow_signals: list[dict[str, Any]]) -> int:
    """Guarda el vector de señales hipotéticas de una corrida. Devuelve filas escritas."""
    if not shadow_signals:
        return 0
    now = datetime.now(UTC).replace(tzinfo=None)  # naive-UTC, como todo el stack
    con = get_connection()
    try:
        _ensure_table(con)
        con.executemany(
            "INSERT INTO shadow_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                [
                    run_id,
                    s.get("model", "unknown"),
                    s["symbol"],
                    s["direction"],
                    s.get("confidence"),
                    s.get("raw_probability"),
                    s.get("size_usd"),
                    now,
                ]
                for s in shadow_signals
            ],
        )
    finally:
        con.close()
    return len(shadow_signals)
