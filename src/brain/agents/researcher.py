"""Bull and Bear researchers + debate facilitator (TradingAgents-inspired)."""

import os as _os

from langchain_core.messages import HumanMessage, SystemMessage

from src.brain.llm import get_llm
from src.brain.state import HermesState

DEBATE_ROUNDS = int(_os.environ.get("DEBATE_ROUNDS", "3"))

BULL_SYSTEM = """You are a bullish crypto researcher. Given analyst reports and market context,
construct the strongest possible case FOR entering a long position. Cite specific signals.
Be rigorous — only argue what the data supports."""

BEAR_SYSTEM = """You are a bearish crypto researcher. Given analyst reports and market context,
construct the strongest possible case AGAINST entering a position (or for shorting).
Cite specific risks, volatility, and unfavorable signals. Be rigorous."""

FACILITATOR_SYSTEM = """You are a debate facilitator for a crypto trading firm.
A QUANT THESIS (LightGBM, deterministic — direction + size) has already been produced.
Your job is to EVALUATE it as red-team: verify, weaken, or overturn via debate.

Rules:
1. The quant thesis provides DIRECTION (BUY or SELL) and SIZE.
2. Your verdict means: AGREE with quant direction, DISAGREE (opposite), or VETO (HOLD).
3. AGREE means the bull/bear support the quant direction — use BUY or SELL matching quant.
4. HOLD means: the debate found compelling evidence AGAINST the quant thesis → VETO.
5. NEVER produce a BUY/SELL that contradicts the quant direction.
6. Confidence reflects signal strength: HIGH = strong agreement, MEDIUM = moderate, LOW = uncertain.

Format: VERDICT: <BUY|SELL|HOLD> | CONFIDENCE: <LOW|MEDIUM|HIGH>
Then provide rationale explaining WHY you agree or disagree with the quant thesis."""

HOLD_THRESHOLD = 0.40  # minimum confidence to avoid HOLD verdict


def _analyst_consensus(state: HermesState) -> str:
    reports = state.get("analyst_reports", [])
    if not reports:
        return "HOLD"
    biases = [r["bias"] for r in reports]
    bullish = sum(1 for b in biases if b == "BULLISH")
    bearish = sum(1 for b in biases if b == "BEARISH")
    if bullish > bearish:
        return "BUY"
    if bearish > bullish:
        return "SELL"
    return "HOLD"


def _reports_text(state: HermesState) -> str:
    return "\n\n".join(
        f"{r['symbol']} ({r['bias']}): {r['analysis']}" for r in state.get("analyst_reports", [])
    )


def bull_researcher(state: HermesState) -> dict:
    llm = get_llm("decision")
    reports = _reports_text(state)
    response = llm.invoke(
        [
            SystemMessage(content=BULL_SYSTEM),
            HumanMessage(
                content=f"Analyst reports:\n{reports}\n\nMarket context: {state.get('regime_summary', '')}\n\nMake the bull case."
            ),
        ]
    )
    return {
        "bull_argument": response.content,
        "messages": [HumanMessage(content=f"[BullResearcher]\n{response.content}")],
    }


def bear_researcher(state: HermesState) -> dict:
    llm = get_llm("decision")
    reports = _reports_text(state)
    response = llm.invoke(
        [
            SystemMessage(content=BEAR_SYSTEM),
            HumanMessage(
                content=f"Analyst reports:\n{reports}\n\nMarket context: {state.get('regime_summary', '')}\n\nMake the bear case."
            ),
        ]
    )
    return {
        "bear_argument": response.content,
        "messages": [HumanMessage(content=f"[BearResearcher]\n{response.content}")],
    }


def debate_facilitator(state: HermesState) -> dict:
    llm = get_llm("decision")
    rounds = state.get("debate_rounds", [])
    round_num = state.get("debate_round_count", 0) + 1
    quant = state.get("quant_signal", {})

    # Each round: bull responds to bear, bear responds to bull
    if round_num <= DEBATE_ROUNDS:
        bull_response = llm.invoke(
            [
                SystemMessage(content=BULL_SYSTEM),
                HumanMessage(
                    content=(
                        f"Bear argument: {state.get('bear_argument', '')}\n\n"
                        "Counter this argument with specific data points."
                    )
                ),
            ]
        )
        bear_response = llm.invoke(
            [
                SystemMessage(content=BEAR_SYSTEM),
                HumanMessage(
                    content=(
                        f"Bull argument: {state.get('bull_argument', '')}\n\n"
                        "Counter this argument with specific data points."
                    )
                ),
            ]
        )
        rounds.append(
            {
                "round": round_num,
                "bull": bull_response.content,
                "bear": bear_response.content,
            }
        )
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

    # Final facilitation — evaluate the quant thesis
    debate_text = "\n\n".join(
        f"Round {r['round']} — Bull: {r['bull']}\nBear: {r['bear']}" for r in rounds
    )

    analyst_consensus = _analyst_consensus(state)
    quant_dir = quant.get("direction", "HOLD")
    quant_rationale = quant.get("rationale", "No quant thesis available")
    quant_size = quant.get("size_usd", 0.0)

    response = llm.invoke(
        [
            SystemMessage(content=FACILITATOR_SYSTEM),
            HumanMessage(
                content=(
                    f"QUANT THESIS (to be verified by debate):\n"
                    f"  Direction: {quant_dir}\n"
                    f"  Size: ${quant_size:.2f}\n"
                    f"  Basis: {quant_rationale}\n\n"
                    f"Analyst consensus direction: {analyst_consensus}\n\n"
                    f"Initial bull: {state.get('bull_argument', '')}\n"
                    f"Initial bear: {state.get('bear_argument', '')}\n\n"
                    f"Debate rounds:\n{debate_text}\n\n"
                    f"Declare your verdict: AGREE (match quant direction), or HOLD (veto)."
                )
            ),
        ]
    )

    text = response.content
    verdict = analyst_consensus if analyst_consensus != "HOLD" else "HOLD"
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

    if confidence < HOLD_THRESHOLD and verdict != "HOLD":
        verdict = "HOLD"

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
