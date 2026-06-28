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
