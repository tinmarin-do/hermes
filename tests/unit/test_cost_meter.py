"""Unit tests for the LLM cost meter — pricing, accumulation, token extraction.

No network: we feed fake LLMResult-shaped objects to the callback.
"""

from types import SimpleNamespace

import pytest

from src.brain import cost_meter
from src.brain.cost_meter import (
    CostCallbackHandler,
    CostMeter,
    estimate_cost_usd,
    mark_logged,
    persist_run,
    start_run,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _pricing(monkeypatch):
    """Pin pricing so cost math is deterministic regardless of .envrc."""
    monkeypatch.setenv("LLM_COST_DEEPSEEK_FLASH_INPUT", "0.14")
    monkeypatch.setenv("LLM_COST_DEEPSEEK_FLASH_OUTPUT", "0.28")


def test_cost_math():
    m = CostMeter(run_id="r1")
    m.add(1_000_000, 1_000_000)  # 1M in, 1M out
    assert m.total_tokens == 2_000_000
    assert m.cost_usd == pytest.approx(0.42)  # 0.14 + 0.28


def test_accumulation_across_calls():
    m = CostMeter(run_id="r1")
    m.add(100, 50)
    m.add(200, 100)
    assert m.n_calls == 2
    assert m.prompt_tokens == 300
    assert m.completion_tokens == 150


def test_callback_routes_to_active_meter():
    meter = start_run("run-x")
    handler = CostCallbackHandler()
    # OpenAI/DeepSeek-shaped llm_output
    resp = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 500, "completion_tokens": 200}},
        generations=[],
    )
    handler.on_llm_end(resp)
    assert meter.prompt_tokens == 500
    assert meter.completion_tokens == 200
    assert meter.n_calls == 1


def test_callback_extracts_from_usage_metadata():
    meter = start_run("run-y")
    handler = CostCallbackHandler()
    msg = SimpleNamespace(usage_metadata={"input_tokens": 80, "output_tokens": 40})
    gen = SimpleNamespace(message=msg)
    resp = SimpleNamespace(llm_output=None, generations=[[gen]])
    handler.on_llm_end(resp)
    assert meter.prompt_tokens == 80
    assert meter.completion_tokens == 40


def test_callback_noop_without_active_meter():
    # Reset active meter to None by setting a fresh context value.
    cost_meter._active_meter.set(None)
    handler = CostCallbackHandler()
    resp = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        generations=[],
    )
    handler.on_llm_end(resp)  # must not raise
    assert cost_meter.current_meter() is None


def test_estimate_baseline_when_no_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "est.duckdb"))
    # 150K tokens, 70/30 split → (105000*0.14 + 45000*0.28)/1e6
    expected = (105_000 / 1e6) * 0.14 + (45_000 / 1e6) * 0.28
    assert estimate_cost_usd() == pytest.approx(round(expected, 4))


def test_persist_and_history_average(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "hist.duckdb"))
    m = start_run("run-persist")
    m.add(1_000_000, 0)  # cost = 0.14
    persist_run(m)
    # Now the estimate should reflect history (avg of the single run = 0.14).
    assert estimate_cost_usd() == pytest.approx(0.14)


def _count_unlogged(monkeypatch_db_path):
    from src.data.db import get_connection

    con = get_connection()
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM llm_cost_runs WHERE NOT logged_to_ledger"
        ).fetchone()
        return row[0]
    finally:
        con.close()


def test_persist_starts_unlogged(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "flag.duckdb"))
    persist_run(start_run("11111111-aaaa-bbbb-cccc-dddddddddddd"))
    assert _count_unlogged(monkeypatch) == 1


def test_mark_logged_flips_flag_by_full_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "flag.duckdb"))
    rid = "11111111-aaaa-bbbb-cccc-dddddddddddd"
    persist_run(start_run(rid))
    assert mark_logged(rid) == 1
    assert _count_unlogged(monkeypatch) == 0


def test_mark_logged_accepts_short_prefix(tmp_path, monkeypatch):
    """The markdown ledger stores the 8-char form; the flip must match by prefix."""
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "flag.duckdb"))
    rid = "abcd1234-aaaa-bbbb-cccc-dddddddddddd"
    persist_run(start_run(rid))
    assert mark_logged("abcd1234") == 1
    assert _count_unlogged(monkeypatch) == 0


def test_mark_logged_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "flag.duckdb"))
    rid = "22222222-aaaa-bbbb-cccc-dddddddddddd"
    persist_run(start_run(rid))
    assert mark_logged(rid) == 1
    assert mark_logged(rid) == 0  # already logged → no rows touched


def test_mark_logged_unknown_id_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_DUCKDB_PATH", str(tmp_path / "flag.duckdb"))
    persist_run(start_run("33333333-aaaa-bbbb-cccc-dddddddddddd"))
    assert mark_logged("ffffffff") == 0
    assert _count_unlogged(monkeypatch) == 1
