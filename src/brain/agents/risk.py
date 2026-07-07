"""Risk team — 3 perspectives + facilitator. Applies Kelly + VaR guardrails."""

import math
import os

from langchain_core.messages import HumanMessage, SystemMessage

from src.brain.llm import get_llm
from src.brain.news_verify import apply_news_modifier
from src.brain.state import HermesState

PERSPECTIVES = [
    (
        "conservative",
        "Guard the downside: reject trades where 2σ VaR exceeds 50% of daily loss limit "
        "or Kelly size is unbacked by signal quality. When in doubt, cut size by 40% rather than reject. "
        "Goal: minimize false approvals (Type I error).",
    ),
    (
        "neutral",
        "Optimize for Sharpe: approve if expected return ≈ 2× the VaR at 2σ. "
        "Adjust size with measured confidence — no binary kills, use scaling. "
        "Goal: balance precision and recall.",
    ),
    (
        "aggressive",
        "Maximize risk-adjusted return: approve unless VaR clearly breaches the daily loss "
        "limit OR the trade direction contradicts the regime. Accept moderate drawdown up to the limit. "
        "Goal: minimize false rejections (Type II error).",
    ),
]

FACILITATOR_SYSTEM = """You are the risk facilitator. Three risk agents have evaluated a trade
with measured goals (conservative guards against false approvals, aggressive against false rejections,
neutral balances Sharpe). Synthesize their views and produce a verdict:

APPROVED: <YES|NO>
ADJUSTED_SIZE_USD: <number or UNCHANGED>
RATIONALE: <quantified reason with at least one number (VaR, Kelly, or confidence)>

Default to YES if at least 2 of 3 recommend approval. Default to NO only with unanimous rejection."""


def _kelly_size(confidence: float, capital: float, fraction: float = 0.25) -> float:
    kelly = confidence * fraction
    return round(capital * kelly, 2)


def _var_check(garch_vol: float | None, size_usd: float, daily_limit_pct: float) -> bool:
    if garch_vol is None:
        return True
    var_2sigma = size_usd * garch_vol * 2 * math.sqrt(24)
    daily_limit = float(os.environ.get("HERMES_CAPITAL_USD", "1")) * daily_limit_pct
    return var_2sigma <= daily_limit


def make_risk_agent(perspective: str, description: str):
    def risk_agent(state: HermesState) -> dict:
        decision = state.get("trader_decision", {})
        confidence = state.get("debate_confidence", 0.5)
        capital = float(os.environ.get("HERMES_CAPITAL_USD", "1"))
        daily_limit = float(os.environ.get("HERMES_DAILY_LOSS_LIMIT_PCT", "0.02"))
        kelly_fraction = float(os.environ.get("HERMES_KELLY_FRACTION", "0.10"))

        symbol = decision.get("symbol", "NONE")
        action = decision.get("action", "HOLD")
        signal = next((s for s in state.get("gold_signals", []) if s["symbol"] == symbol), None)

        news_conf, news_note = apply_news_modifier(confidence, signal, action)
        effective_confidence = news_conf

        size = _kelly_size(effective_confidence, capital, kelly_fraction)
        garch_vol = signal["features"]["garch_vol"] if signal else None
        var_ok = _var_check(garch_vol, size, daily_limit)

        news_context = f"\nNews verification: {news_note}" if news_note else ""

        llm = get_llm("decision")
        response = llm.invoke(
            [
                SystemMessage(content=f"You are the {perspective} risk agent. {description}"),
                HumanMessage(
                    content=(
                        f"Trade: {action} {symbol}\n"
                        f"Debate confidence: {confidence:.0%}\n"
                        f"Effective confidence (after news adjustment): {effective_confidence:.0%}\n"
                        f"Proposed size: ${size:.2f} (Kelly {kelly_fraction}× · effective conf {effective_confidence:.0%})\n"
                        f"GARCH vol: {garch_vol} | VaR 2σ check: {'✅ PASS' if var_ok else '❌ FAIL'}\n"
                        f"Daily loss limit: {daily_limit:.0%} of ${capital}\n"
                        f"Trader rationale: {decision.get('rationale', '')[:300]}\n"
                        f"{news_context}\n"
                        "Assess this trade from your risk perspective in 2-3 sentences. "
                        "State: APPROVE or REJECT, and any size adjustment."
                    )
                ),
            ]
        )

        report = {
            "perspective": perspective,
            "size_usd": size,
            "var_ok": var_ok,
            "assessment": response.content,
        }
        return {
            "risk_reports": [report],
            "messages": [HumanMessage(content=f"[Risk:{perspective}]\n{response.content}")],
        }

    risk_agent.__name__ = f"risk_{perspective}"
    return risk_agent


def risk_facilitator(state: HermesState) -> dict:
    llm = get_llm("decision")
    reports = state.get("risk_reports", [])
    reports_text = "\n\n".join(
        f"{r['perspective'].upper()} (size=${r['size_usd']}, VaR={'OK' if r['var_ok'] else 'FAIL'}):\n{r['assessment']}"
        for r in reports
    )

    response = llm.invoke(
        [
            SystemMessage(content=FACILITATOR_SYSTEM),
            HumanMessage(content=f"Risk team assessments:\n{reports_text}"),
        ]
    )

    text = response.content
    approved = "APPROVED: YES" in text.upper() or "APPROVED:YES" in text.upper()

    # GATE DURO (revisión final 2026-07-06): el VaR calibrado es un guardrail
    # determinista (regla #4) — el LLM puede FRENAR un trade que pasó el VaR,
    # pero JAMÁS aprobar uno que lo reprobó. Antes esto era solo advisory: un
    # facilitador persuadido podía soltar el freno. Los agentes solo frenan.
    var_ok = all(r.get("var_ok", True) for r in reports)
    if approved and not var_ok:
        approved = False
        text += "\n[GATE] VaR 2σ reprobado — aprobación del LLM anulada por guardrail (§8.2)."

    return {
        "risk_synthesis": text,
        "risk_approved": approved,
        "messages": [HumanMessage(content=f"[RiskFacilitator]\n{text}")],
    }
