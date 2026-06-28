"""Portfolio allocator — deterministic budget split across symbols (§8.8).

Runs AFTER the LLM committee (debate → risk → PM). The agents act as the GLOBAL brake:
risk approval + debate verdict gate how much of the budget is deployed (`global_mult`).
This node then splits that deployable budget across the per-symbol quant signals by
`confidence × inverse-vol`, enforces the conservative short cap, and computes the orders
as the DELTA between the target weights and the current book.

Pure and deterministic — `compute_allocations` carries the whole logic and is unit-tested.
Shorts are capped here (deterministic risk control, stricter and more data-first than an LLM).
"""

import os

# Mínimo absoluto de la vol GARCH para evitar dividir por ~0 al ponderar inverse-vol.
_VOL_FLOOR = 1e-4


def compute_allocations(
    quant_signals: list[dict],
    current_positions: list[dict],
    budget: float,
    global_mult: float,
    short_cap_pct: float = 0.10,
    min_trade_frac: float = 0.01,
) -> list[dict]:
    """Target-weight rebalancing (§8.8).

    Weights: ``w_i ∝ confidence_i / garch_vol_i`` over actionable signals (BUY long,
    SELL short), normalized. Shorts are signed negative and their gross weight is capped
    at ``short_cap_pct`` of the budget (freed weight → cash). Each leg's order is the delta
    between its target USD and the current signed notional held; day 0 (empty book) reduces
    to deploying the targets directly.
    """
    deployable = max(budget, 0.0) * max(0.0, min(1.0, global_mult))

    actionable = [
        s
        for s in quant_signals
        if s.get("direction") in ("BUY", "SELL") and (s.get("confidence") or 0.0) > 0
    ]

    raw: dict[str, float] = {}
    for s in actionable:
        gv = max(s.get("garch_vol") or 0.0, _VOL_FLOOR)
        raw[s["symbol"]] = (s["confidence"] or 0.0) / gv
    total = sum(raw.values())

    target_w: dict[str, float] = {}
    if total > 0:
        for s in actionable:
            w = raw[s["symbol"]] / total
            target_w[s["symbol"]] = w if s["direction"] == "BUY" else -w

    # ── Cap de exposición corta (§8.8): Σ|short weight| ≤ short_cap_pct ──
    short_sum = sum(-w for w in target_w.values() if w < 0)
    if short_sum > short_cap_pct > 0:
        scale = short_cap_pct / short_sum
        target_w = {k: (w * scale if w < 0 else w) for k, w in target_w.items()}

    # ── Libro actual: notional firmado por símbolo (BUY +, SELL/short −) ──
    current_usd: dict[str, float] = {}
    for p in current_positions:
        sgn = 1.0 if p.get("action") == "BUY" else -1.0
        px = p.get("current_price") or p.get("entry_price") or 0.0
        qty = p.get("quantity") or 0.0
        current_usd[p["symbol"]] = current_usd.get(p["symbol"], 0.0) + sgn * qty * px

    min_trade = budget * min_trade_frac
    legs: list[dict] = []
    for sym in sorted(set(target_w) | set(current_usd)):
        tw = target_w.get(sym, 0.0)
        target_usd = round(deployable * tw, 4)
        cur = round(current_usd.get(sym, 0.0), 4)
        delta = round(target_usd - cur, 4)

        if abs(delta) < min_trade:
            action = "HOLD"
        elif delta > 0:
            action = "BUY"
        else:
            action = "SELL"

        legs.append(
            {
                "symbol": sym,
                "target_weight": round(tw, 4),
                "target_usd": target_usd,
                "current_usd": cur,
                "action": action,
                "size_usd": round(abs(delta), 4),
            }
        )
    return legs


def allocator_node(state: dict) -> dict:
    """LangGraph node: derive the global brake from the committee, then split the budget."""
    budget = float(os.environ.get("HERMES_CAPITAL_USD", "500"))
    short_cap = float(os.environ.get("HERMES_SHORT_CAP_PCT", "0.10"))

    risk_approved = state.get("risk_approved", False)
    verdict = state.get("debate_verdict", "HOLD")
    debate_conf = state.get("debate_confidence", 0.0)

    # Agentes como freno GLOBAL: si riesgo rechaza o el debate dice HOLD → no se despliega
    # nada nuevo (todo a cash). Si aprueba → despliega proporcional a la convicción.
    global_mult = max(0.0, min(1.0, debate_conf)) if (risk_approved and verdict != "HOLD") else 0.0

    legs = compute_allocations(
        state.get("quant_signals", []),
        state.get("current_positions", []),
        budget,
        global_mult,
        short_cap_pct=short_cap,
    )
    return {"allocations": legs}
