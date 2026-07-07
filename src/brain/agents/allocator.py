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
    min_trade_frac: float = 0.05,  # banda anti-churn (2026-07-06); antes 0.01 solo filtraba polvo
    fee_reserve_pct: float = 0.0,
    freeze: bool = False,
    pocket_free: dict[str, float] | None = None,
    symbol_pocket: dict[str, str] | None = None,
) -> list[dict]:
    """Target-weight rebalancing (§8.8).

    Weights: ``w_i ∝ confidence_i / garch_vol_i`` over actionable signals (BUY long,
    SELL short), normalized. Shorts are signed negative and their gross weight is capped
    at ``short_cap_pct`` of the budget (freed weight → cash). Each leg's order is the delta
    between its target USD and the current signed notional held; day 0 (empty book) reduces
    to deploying the targets directly.

    ``freeze=True`` = freno global SIN convicción (verdict HOLD / risk rechaza): el libro
    queda COMO ESTÁ (targets = posiciones actuales → 0 órdenes). Antes esto liquidaba todo
    (targets $0) — churn/fees en cada día sin convicción. La liquidación de emergencia
    tiene su propio camino (/execution:kill).

    ``fee_reserve_pct`` recorta el budget desplegable para que el último BUY del rebalanceo
    no rebote por los fees (BUY debita size+fee; a escala $400 los centavos importan).
    """
    # ── Libro actual: notional firmado por símbolo (BUY +, SELL/short −) ──
    current_usd: dict[str, float] = {}
    for p in current_positions:
        sgn = 1.0 if p.get("action") == "BUY" else -1.0
        px = p.get("current_price") or p.get("entry_price") or 0.0
        qty = p.get("quantity") or 0.0
        current_usd[p["symbol"]] = current_usd.get(p["symbol"], 0.0) + sgn * qty * px

    if freeze:
        return [
            {
                "symbol": sym,
                "target_weight": round(current_usd[sym] / budget, 4) if budget > 0 else 0.0,
                "target_usd": round(current_usd[sym], 4),
                "current_usd": round(current_usd[sym], 4),
                "action": "HOLD",
                "size_usd": 0.0,
            }
            for sym in sorted(current_usd)
        ]

    deployable = max(budget, 0.0) * max(0.0, min(1.0, global_mult))
    deployable *= 1.0 - max(0.0, min(1.0, fee_reserve_pct))

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

    # ── Cap por bolsillo de quote (hallazgo 2026-07-03, corrida 29cb1a50): el budget
    # es UNO (equity) pero la caja vive en bolsillos por moneda de quote (Bitso:
    # USDT para BTC/ETH/SOL/XRP · USD para LINK/AVAX). Los BUYs de un bolsillo no
    # pueden exceder su caja libre + lo que liberan los SELLs del MISMO bolsillo
    # (el runner ejecuta SELLs primero). El excedente queda en cash — determinista,
    # sin redistribuir a otros símbolos.
    if pocket_free and symbol_pocket:
        for pocket in set(symbol_pocket.values()):
            in_pocket = [a for a in legs if symbol_pocket.get(a["symbol"]) == pocket]
            sell_proceeds = sum(a["size_usd"] for a in in_pocket if a["action"] == "SELL") * (
                1.0 - max(0.0, min(1.0, fee_reserve_pct))
            )
            available = max(0.0, pocket_free.get(pocket, 0.0)) + sell_proceeds
            buys = [a for a in in_pocket if a["action"] == "BUY"]
            need = sum(a["size_usd"] for a in buys)
            if need > available > 0:
                scale = available / need
                for a in buys:
                    a["size_usd"] = round(a["size_usd"] * scale, 4)
                    a["target_usd"] = round(a["current_usd"] + a["size_usd"], 4)
                    if a["size_usd"] < min_trade:
                        a["action"], a["size_usd"] = "HOLD", 0.0
            elif need > 0 and available <= 0:
                for a in buys:
                    a["action"], a["size_usd"] = "HOLD", 0.0
    return legs


def allocator_node(state: dict) -> dict:
    """LangGraph node: derive the global brake from the committee, then split the budget."""
    budget = float(os.environ.get("HERMES_CAPITAL_USD", "1"))
    short_cap = float(os.environ.get("HERMES_SHORT_CAP_PCT", "0.10"))
    fee_reserve = float(os.environ.get("HERMES_FEE_RESERVE_PCT", "0.005"))
    # Banda anti-churn (auditoría de cadencia 2026-07-06, decisión Erika opción B):
    # el champion se validó SEMANAL; producción evalúa diario → solo cambios
    # MATERIALES operan (≥5% del budget). El backtest acotó: evaluar diario aporta
    # (+99.8% sin fees) pero el churn sin control es letal (−93% con round-trip
    # diario a 36bps). El turnover real del track record decide en ~30 días (§8.9).
    min_trade = float(os.environ.get("HERMES_MIN_TRADE_FRAC", "0.05"))

    risk_approved = state.get("risk_approved", False)
    verdict = state.get("debate_verdict", "HOLD")
    debate_conf = state.get("debate_confidence", 0.0)

    # Agentes como freno GLOBAL: si riesgo rechaza o el debate dice HOLD → el libro se
    # CONGELA (0 órdenes, nada nuevo se despliega — decisión 2026-07-03, antes liquidaba).
    # Si aprueba → despliega proporcional a la convicción.
    brake = not risk_approved or verdict == "HOLD"
    global_mult = 0.0 if brake else max(0.0, min(1.0, debate_conf))

    legs = compute_allocations(
        state.get("quant_signals", []),
        state.get("current_positions", []),
        budget,
        global_mult,
        short_cap_pct=short_cap,
        min_trade_frac=min_trade,
        fee_reserve_pct=fee_reserve,
        freeze=brake,
        pocket_free=state.get("pocket_free"),
        symbol_pocket=state.get("symbol_pocket"),
    )
    return {"allocations": legs}
