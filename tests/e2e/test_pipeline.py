"""End-to-end pipeline test — Gold → agents → paper execution.

This is the real thing: it invokes the actual LangGraph pipeline, which calls the
DeepSeek API (paid, ~$0.007/run) and reads Gold signals from DuckDB. It is NOT run
in CI (CI is `-m unit` only); it's for local validation in paper mode, like the
integration suite is for Binance testnet.

The whole pipeline runs ONCE (session-scoped fixture) and every test asserts a facet
of that single run's contract + guardrail invariants, so we pay for exactly one LLM
call. The suite auto-skips when prerequisites are missing (no API key, no Gold data)
so it never fails spuriously.

Run with:  uv run pytest tests/e2e/ -m e2e -v
"""

import os
import uuid

import pytest

from src.brain.runner import run
from src.data.gold.aggregate import aggregate

pytestmark = pytest.mark.e2e

SYMBOLS = ["BTC/USDT", "ETH/USDT"]
TIMEFRAME = "1h"
ACTIONS = {"BUY", "SELL", "HOLD"}


@pytest.fixture(scope="session")
def pipeline_run():
    """Run the full pipeline once in local/paper mode; share the result.

    Skips (not fails) when the real prerequisites aren't there: the DeepSeek API
    key and ingested Gold signals. That keeps `pytest tests/e2e/` green on a fresh
    checkout while still exercising the real path when the stack is up.
    """
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY not set — e2e needs the real LLM")
    if not aggregate(SYMBOLS, TIMEFRAME):
        pytest.skip("No Gold signals — run /data:aggregate-gold first")

    os.environ["HERMES_MODE"] = "local"
    os.environ["EXCHANGE_MODE"] = "paper"
    return run(symbols=SYMBOLS, timeframe=TIMEFRAME)


def test_run_returns_valid_run_id(pipeline_run):
    uuid.UUID(pipeline_run["run_id"])  # raises if not a valid UUID


def test_debate_verdict_in_vocabulary(pipeline_run):
    assert pipeline_run["debate_verdict"] in ACTIONS
    assert 0.0 <= pipeline_run["debate_confidence"] <= 1.0


def test_risk_check_ran(pipeline_run):
    assert isinstance(pipeline_run["risk_approved"], bool)


def test_pm_decision_well_formed(pipeline_run):
    pm = pipeline_run["pm_decision"]
    assert pm.get("action") in ACTIONS
    assert float(pm.get("size_usd", 0)) >= 0.0


def test_asymmetric_veto_invariant(pipeline_run):
    """§8.7.2: a HOLD debate verdict must brake the PM — no trade originated."""
    if pipeline_run["debate_verdict"] == "HOLD":
        assert pipeline_run["pm_decision"]["action"] == "HOLD"


def test_no_trade_without_risk_approval(pipeline_run):
    """A live order may only exist when risk approved AND action isn't HOLD."""
    pm = pipeline_run["pm_decision"]
    if not pipeline_run["risk_approved"] or pm["action"] == "HOLD":
        assert pipeline_run["order_result"] is None


def test_hold_executes_no_order(pipeline_run):
    if pipeline_run["pm_decision"]["action"] == "HOLD":
        assert pipeline_run["order_result"] is None


def test_order_consistent_with_decision(pipeline_run):
    """If an order was placed, it must match the PM decision."""
    order = pipeline_run["order_result"]
    if order is not None:
        pm = pipeline_run["pm_decision"]
        assert order["action"] == pm["action"]
        assert order["symbol"] == pm["symbol"]
        assert pipeline_run["risk_approved"] is True


def test_paper_account_state_present(pipeline_run):
    assert isinstance(pipeline_run["positions"], list)
    assert float(pipeline_run["balance"]) >= 0.0


def test_llm_cost_measured(pipeline_run):
    """cost_meter must have captured real token usage for the run."""
    cost = pipeline_run["cost"]
    assert cost["n_calls"] > 0
    assert cost["total_tokens"] > 0
    assert cost["cost_usd"] >= 0.0
