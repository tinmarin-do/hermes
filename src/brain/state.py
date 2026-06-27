"""Global agent state — single source of truth across all nodes."""
import operator
from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class HermesState(TypedDict):
    # Run metadata
    run_id: str
    symbols: list[str]
    timeframe: str

    # Data layer
    gold_signals: list[dict]

    # Regime classification
    regime_summary: str

    # Analyst reports (one per symbol) — written by parallel analyst nodes,
    # so it needs an additive reducer to merge concurrent branches.
    analyst_reports: Annotated[list[dict], operator.add]

    # Bull/bear debate
    bull_argument: str
    bear_argument: str
    debate_rounds: list[dict]
    debate_round_count: int
    debate_verdict: str               # "BUY" | "SELL" | "HOLD"
    debate_confidence: float

    # Trader decision
    trader_decision: dict             # {action, symbol, rationale}

    # Risk team (3 perspectives) — written by parallel risk nodes, additive reducer.
    risk_reports: Annotated[list[dict], operator.add]
    risk_synthesis: str
    risk_approved: bool

    # Portfolio Manager final call
    pm_decision: dict                 # {action, symbol, size_usd, rationale}

    # Message history (for audit / dashboard visor de debate)
    messages: Annotated[list, add_messages]
