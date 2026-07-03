"""LLM cost metering — captures real DeepSeek token usage per run.

Closes the cost-tracking gap: every `get_llm()` call attaches a callback that
accumulates prompt/completion tokens into the run's active meter. At the end of
a run the actual USD cost is computed from `.envrc` pricing, persisted to DuckDB
(`llm_cost_runs`), and returned so the `/cost:gate` (pre-run estimate) and
`/cost:log` (post-run actual) skills can surface it — WITHOUT the code ever
writing the markdown ledger directly (regla crítica #5).

Pricing comes from env (per 1M tokens):
  LLM_COST_DEEPSEEK_FLASH_INPUT   (default 0.14)
  LLM_COST_DEEPSEEK_FLASH_OUTPUT  (default 0.28)
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

# Active meter for the current run. ContextVar so concurrent runs don't bleed.
_active_meter: ContextVar[CostMeter | None] = ContextVar("_active_meter", default=None)


def _price_input() -> float:
    return float(os.environ.get("LLM_COST_DEEPSEEK_FLASH_INPUT", "0.14"))


def _price_output() -> float:
    return float(os.environ.get("LLM_COST_DEEPSEEK_FLASH_OUTPUT", "0.28"))


@dataclass
class CostMeter:
    """Accumulates token usage across all LLM calls in one run."""

    run_id: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    n_calls: int = 0

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += int(prompt or 0)
        self.completion_tokens += int(completion or 0)
        self.n_calls += 1

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> float:
        cost = (self.prompt_tokens / 1_000_000) * _price_input() + (
            self.completion_tokens / 1_000_000
        ) * _price_output()
        return round(cost, 4)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "n_calls": self.n_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
        }


class CostCallbackHandler(BaseCallbackHandler):
    """Attached to every LLM via get_llm — routes token usage to the active meter."""

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        meter = _active_meter.get()
        if meter is None:
            return
        prompt, completion = _extract_tokens(response)
        meter.add(prompt, completion)


def _extract_tokens(response: Any) -> tuple[int, int]:
    """Pull (prompt, completion) tokens from a LangChain LLMResult, robust to shape."""
    # Path 1: aggregated llm_output (OpenAI-compatible, incl. DeepSeek).
    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if usage:
        return (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))

    # Path 2: per-generation usage_metadata (newer LangChain).
    prompt = completion = 0
    for gen_list in getattr(response, "generations", []) or []:
        for gen in gen_list:
            msg = getattr(gen, "message", None)
            meta = getattr(msg, "usage_metadata", None) or {}
            prompt += meta.get("input_tokens", 0)
            completion += meta.get("output_tokens", 0)
    return (prompt, completion)


def start_run(run_id: str) -> CostMeter:
    """Begin metering for a run. Sets the active meter and returns it."""
    meter = CostMeter(run_id=run_id)
    _active_meter.set(meter)
    return meter


def current_meter() -> CostMeter | None:
    return _active_meter.get()


def estimate_cost_usd(default_total_tokens: int = 150_000) -> float:
    """Pre-run estimate, data-driven: average of past runs, else a token baseline.

    Used to feed `/cost:gate` BEFORE invoking models so spend is never a surprise.
    """
    avg = _historical_avg_cost()
    if avg is not None:
        return round(avg, 4)
    # Fallback baseline: 70% input / 30% output split of a typical full run.
    p_in = int(default_total_tokens * 0.7)
    p_out = default_total_tokens - p_in
    return round((p_in / 1_000_000) * _price_input() + (p_out / 1_000_000) * _price_output(), 4)


def _historical_avg_cost(last_n: int = 10) -> float | None:
    try:
        from src.data.db import get_connection

        con = get_connection()
        try:
            _ensure_table(con)
            row = con.execute(
                "SELECT AVG(cost_usd) FROM (SELECT cost_usd FROM llm_cost_runs "
                "ORDER BY ts DESC LIMIT ?)",
                [last_n],
            ).fetchone()
        finally:
            con.close()
        return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None


def _ensure_table(con: Any) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS llm_cost_runs (
            run_id            VARCHAR NOT NULL,
            ts                TIMESTAMP NOT NULL,
            n_calls           INTEGER NOT NULL,
            prompt_tokens     INTEGER NOT NULL,
            completion_tokens INTEGER NOT NULL,
            total_tokens      INTEGER NOT NULL,
            cost_usd          DOUBLE NOT NULL,
            logged_to_ledger  BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (run_id, ts)
        )
    """)


def persist_run(meter: CostMeter) -> None:
    """Persist actual usage to DuckDB so /cost:log can append it to the ledger."""
    from src.data.db import get_connection

    con = get_connection()
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        _ensure_table(con)
        con.execute(
            """INSERT INTO llm_cost_runs
               (run_id, ts, n_calls, prompt_tokens, completion_tokens,
                total_tokens, cost_usd, logged_to_ledger)
               VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)""",
            [
                meter.run_id,
                now,
                meter.n_calls,
                meter.prompt_tokens,
                meter.completion_tokens,
                meter.total_tokens,
                meter.cost_usd,
            ],
        )
    finally:
        con.close()


def mark_logged(run_id: str) -> int:
    """Flip `logged_to_ledger=TRUE` after `/cost:log` appended the run to the
    markdown ledger, so `/cost:status` stops flagging it as unregistered.

    Accepts a full run_id or a unique prefix — the markdown ledger stores the
    short 8-char form while DuckDB keeps the full UUID. Only unlogged matches are
    touched (idempotent). Returns the number of rows updated.
    """
    from src.data.db import get_connection

    con = get_connection()
    try:
        _ensure_table(con)
        rows = con.execute(
            "UPDATE llm_cost_runs SET logged_to_ledger = TRUE "
            "WHERE run_id LIKE ? AND NOT logged_to_ledger RETURNING run_id",
            [f"{run_id}%"],
        ).fetchall()
        return len(rows)
    finally:
        con.close()


def mark_logged_cloud(run_id: str) -> int:
    """`mark_logged` contra el DuckDB de GCS (las corridas cloud viven ahí, no en el
    archivo local — gap detectado 2026-07-03). Baja SOLO el blob del DB a un tmp,
    flipea el flag y lo re-sube; jamás toca el snapshot (evita pisar el del dashboard
    con uno local viejo). Ventana de carrera con una corrida en vuelo: aceptable en
    POC (1 corrida/día + versioning del bucket)."""
    import tempfile

    from src.brain.state_sync import _bucket

    bucket = _bucket()
    blob = bucket.blob("hermes.duckdb")
    if not blob.exists():
        raise RuntimeError("gs://.../hermes.duckdb no existe — nada que marcar")

    with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as tmp:
        tmp_path = tmp.name
    blob.download_to_filename(tmp_path)

    prev = os.environ.get("HERMES_DUCKDB_PATH")
    os.environ["HERMES_DUCKDB_PATH"] = tmp_path
    try:
        n = mark_logged(run_id)
    finally:
        if prev is None:
            del os.environ["HERMES_DUCKDB_PATH"]
        else:
            os.environ["HERMES_DUCKDB_PATH"] = prev

    if n > 0:
        bucket.blob("hermes.duckdb").upload_from_filename(tmp_path)
    os.unlink(tmp_path)
    return n


if __name__ == "__main__":
    import sys

    # `--mark-logged <run_id> [--cloud]` flips the DuckDB ledger flag — invoked by the
    # /cost:log skill right after it appends the row to the markdown ledger. `--cloud`
    # targets the GCS state DB (corridas del brain en Cloud Run).
    if len(sys.argv) >= 3 and sys.argv[1] == "--mark-logged":
        rid = sys.argv[2]
        if "--cloud" in sys.argv[3:]:
            n = mark_logged_cloud(rid)
            print(f"[cost_meter] (cloud) marked {n} run(s) as logged_to_ledger for '{rid}'")
        else:
            n = mark_logged(rid)
            print(f"[cost_meter] marked {n} run(s) as logged_to_ledger for '{rid}'")
    else:
        print("usage: python -m src.brain.cost_meter --mark-logged <run_id> [--cloud]")
        sys.exit(2)
