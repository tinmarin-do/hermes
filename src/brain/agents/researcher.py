"""Bull and Bear researchers + debate facilitator (TradingAgents-inspired)."""
from langchain_core.messages import HumanMessage, SystemMessage
from src.brain.llm import get_llm
from src.brain.state import HermesState

BULL_SYSTEM = """You are a bullish crypto researcher. Given analyst reports and market context,
construct the strongest possible case FOR entering a long position. Cite specific signals.
Be rigorous — only argue what the data supports."""

BEAR_SYSTEM = """You are a bearish crypto researcher. Given analyst reports and market context,
construct the strongest possible case AGAINST entering a position (or for shorting).
Cite specific risks, volatility, and unfavorable signals. Be rigorous."""

FACILITATOR_SYSTEM = """You are a debate facilitator for a crypto trading firm.
You have heard the bull and bear arguments. Your job is to:
1. Identify the strongest points from each side.
2. Declare a prevailing view: BUY, SELL, or HOLD.
3. State a confidence level: LOW (<50%), MEDIUM (50-70%), HIGH (>70%).
Format: VERDICT: <BUY|SELL|HOLD> | CONFIDENCE: <LOW|MEDIUM|HIGH>
Then provide a 2-3 sentence rationale."""

import os as _os
DEBATE_ROUNDS = int(_os.environ.get("DEBATE_ROUNDS", "2"))


def _reports_text(state: HermesState) -> str:
    return "\n\n".join(
        f"{r['symbol']} ({r['bias']}): {r['analysis']}"
        for r in state.get("analyst_reports", [])
    )


def bull_researcher(state: HermesState) -> dict:
    llm = get_llm("decision")
    reports = _reports_text(state)
    response = llm.invoke([
        SystemMessage(content=BULL_SYSTEM),
        HumanMessage(content=f"Analyst reports:\n{reports}\n\nMarket context: {state.get('regime_summary', '')}\n\nMake the bull case."),
    ])
    return {
        "bull_argument": response.content,
        "messages": [HumanMessage(content=f"[BullResearcher]\n{response.content}")],
    }


def bear_researcher(state: HermesState) -> dict:
    llm = get_llm("decision")
    reports = _reports_text(state)
    response = llm.invoke([
        SystemMessage(content=BEAR_SYSTEM),
        HumanMessage(content=f"Analyst reports:\n{reports}\n\nMarket context: {state.get('regime_summary', '')}\n\nMake the bear case."),
    ])
    return {
        "bear_argument": response.content,
        "messages": [HumanMessage(content=f"[BearResearcher]\n{response.content}")],
    }


def debate_facilitator(state: HermesState) -> dict:
    llm = get_llm("decision")
    rounds = state.get("debate_rounds", [])
    round_num = state.get("debate_round_count", 0) + 1

    # Each round: bull responds to bear, bear responds to bull
    if round_num <= DEBATE_ROUNDS:
        bull_response = llm.invoke([
            SystemMessage(content=BULL_SYSTEM),
            HumanMessage(content=(
                f"Bear argument: {state.get('bear_argument', '')}\n\n"
                "Counter this argument with specific data points."
            )),
        ])
        bear_response = llm.invoke([
            SystemMessage(content=BEAR_SYSTEM),
            HumanMessage(content=(
                f"Bull argument: {state.get('bull_argument', '')}\n\n"
                "Counter this argument with specific data points."
            )),
        ])
        rounds.append({
            "round": round_num,
            "bull": bull_response.content,
            "bear": bear_response.content,
        })
        return {
            "debate_rounds": rounds,
            "debate_round_count": round_num,
            "bull_argument": bull_response.content,
            "bear_argument": bear_response.content,
            "messages": [
                HumanMessage(content=f"[Debate R{round_num} Bull]\n{bull_response.content}"),
                HumanMessage(content=f"[Debate R{round_num} Bear]\n{bear_response.content}"),
            ],
        }

    # Final facilitation
    debate_text = "\n\n".join(
        f"Round {r['round']} — Bull: {r['bull']}\nBear: {r['bear']}"
        for r in rounds
    )
    response = llm.invoke([
        SystemMessage(content=FACILITATOR_SYSTEM),
        HumanMessage(content=(
            f"Initial bull: {state.get('bull_argument', '')}\n"
            f"Initial bear: {state.get('bear_argument', '')}\n\n"
            f"Debate rounds:\n{debate_text}\n\n"
            "Declare the verdict."
        )),
    ])

    text = response.content
    verdict = "HOLD"
    confidence = 0.5
    for v in ["BUY", "SELL", "HOLD"]:
        if f"VERDICT: {v}" in text.upper():
            verdict = v
    if "HIGH" in text.upper():
        confidence = 0.80
    elif "MEDIUM" in text.upper():
        confidence = 0.60
    elif "LOW" in text.upper():
        confidence = 0.40

    return {
        "debate_verdict": verdict,
        "debate_confidence": confidence,
        "debate_round_count": round_num,
        "messages": [HumanMessage(content=f"[Facilitator]\n{text}")],
    }


def should_continue_debate(state: HermesState) -> str:
    if state.get("debate_round_count", 0) <= DEBATE_ROUNDS:
        return "debate"
    return "trader"
