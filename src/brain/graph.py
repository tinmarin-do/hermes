"""Hermes LangGraph brain — full multi-agent pipeline."""
import os
from langgraph.graph import StateGraph, START, END

from src.brain.state import HermesState
from src.brain.agents.regime import regime_classifier
from src.brain.agents.analyst import make_analyst
from src.brain.agents.researcher import (
    bull_researcher, bear_researcher, debate_facilitator, should_continue_debate,
)
from src.brain.agents.trader import trader
from src.brain.agents.risk import make_risk_agent, risk_facilitator, PERSPECTIVES
from src.brain.agents.pm import portfolio_manager


def build_graph(symbols: list[str] | None = None) -> StateGraph:
    if symbols is None:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    g = StateGraph(HermesState)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    g.add_node("regime_classifier", regime_classifier)

    for sym in symbols:
        node_name = f"analyst_{sym.replace('/', '_')}"
        g.add_node(node_name, make_analyst(sym))

    g.add_node("bull_researcher", bull_researcher)
    g.add_node("bear_researcher", bear_researcher)
    g.add_node("debate_facilitator", debate_facilitator)
    g.add_node("trader", trader)

    for perspective, description in PERSPECTIVES:
        g.add_node(f"risk_{perspective}", make_risk_agent(perspective, description))

    g.add_node("risk_facilitator", risk_facilitator)
    g.add_node("portfolio_manager", portfolio_manager)

    # ── Edges ─────────────────────────────────────────────────────────────────
    # START → regime classifier
    g.add_edge(START, "regime_classifier")

    # regime → all analysts in parallel
    analyst_nodes = [f"analyst_{s.replace('/', '_')}" for s in symbols]
    for node in analyst_nodes:
        g.add_edge("regime_classifier", node)

    # all analysts → bull + bear (parallel)
    for node in analyst_nodes:
        g.add_edge(node, "bull_researcher")
        g.add_edge(node, "bear_researcher")

    # bull + bear → facilitator
    g.add_edge("bull_researcher", "debate_facilitator")
    g.add_edge("bear_researcher", "debate_facilitator")

    # facilitator → loop or continue
    g.add_conditional_edges(
        "debate_facilitator",
        should_continue_debate,
        {"debate": "debate_facilitator", "trader": "trader"},
    )

    # trader → risk team in parallel
    for perspective, _ in PERSPECTIVES:
        g.add_edge("trader", f"risk_{perspective}")
        g.add_edge(f"risk_{perspective}", "risk_facilitator")

    g.add_edge("risk_facilitator", "portfolio_manager")
    g.add_edge("portfolio_manager", END)

    return g.compile()


# Singleton — compile once
hermes_graph = build_graph()
