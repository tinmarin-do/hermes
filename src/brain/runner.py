"""Entry point for one pipeline run — brain → execution."""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from src.brain.graph import hermes_graph
from src.data.gold.aggregate import aggregate
from src.execution.adapter import ExecutionAdapter


def _get_adapter() -> ExecutionAdapter:
    exchange_mode = os.environ.get("EXCHANGE_MODE", "paper")
    if exchange_mode == "live":
        from src.execution.binance import BinanceAdapter

        return BinanceAdapter(mode="live")
    elif exchange_mode == "testnet":
        from src.execution.binance import BinanceAdapter

        return BinanceAdapter(mode="testnet")
    else:
        from src.execution.adapter import PaperAdapter

        # Paper sandbox: el balance se siembra con el budget de trading (§8.8 — $1 local).
        budget = float(os.environ.get("HERMES_CAPITAL_USD", "1"))
        return PaperAdapter(initial_balance=budget)


def run(symbols: list[str] | None = None, timeframe: str = "1h") -> dict[str, Any]:
    if symbols is None:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    gold_signals = aggregate(symbols, timeframe)
    if not gold_signals:
        raise RuntimeError("No Gold signals available — run data:aggregate-gold first")

    run_id = str(uuid.uuid4())

    from src.brain.cost_meter import estimate_cost_usd, persist_run, start_run

    meter = start_run(run_id)
    est = estimate_cost_usd()
    print(
        f"[cost] estimado LLM de esta corrida: ~${est:.4f} USD "
        f"(autorizar via /cost:gate antes de corridas programadas)",
        flush=True,
    )

    # Inyectar el libro ACTUAL al estado ANTES del grafo (§8.8): el allocator rebalancea
    # por delta contra lo que ya se tiene. El mismo adapter se reutiliza para ejecutar.
    adapter = _get_adapter()
    positions_before = adapter.get_positions()
    current_positions = [
        {
            "symbol": p.symbol,
            "action": p.action,
            "quantity": p.quantity,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "unrealized_pnl": p.unrealized_pnl,
        }
        for p in positions_before
    ]

    initial_state: dict[str, Any] = {
        "run_id": run_id,
        "symbols": symbols,
        "timeframe": timeframe,
        "gold_signals": gold_signals,
        "regime_summary": "",
        "quant_signal": {},
        "quant_signals": [],
        "shadow_signals": [],
        "current_positions": current_positions,
        "allocations": [],
        "analyst_reports": [],
        "bull_argument": "",
        "bear_argument": "",
        "debate_rounds": [],
        "debate_round_count": 0,
        "debate_verdict": "HOLD",
        "debate_confidence": 0.5,
        "trader_decision": {},
        "risk_reports": [],
        "risk_synthesis": "",
        "risk_approved": False,
        "pm_decision": {},
        "messages": [],
    }

    print(f"[runner] streaming · run_id={run_id} · symbols={symbols}", flush=True)
    final_state: dict[str, Any] = initial_state
    for mode, chunk in hermes_graph.stream(  # type: ignore[attr-defined]
        initial_state, stream_mode=["updates", "values"]
    ):
        if mode == "updates":
            for node, update in (chunk or {}).items():
                detail = ""
                if update:
                    if "quant_signal" in update:
                        qs = update["quant_signal"]
                        detail = f" · {qs.get('direction', '?')} ${qs.get('size_usd', 0):.2f}"
                    elif "debate_round_count" in update:
                        detail = f" · round={update['debate_round_count']}"
                    elif "debate_verdict" in update:
                        detail = f" · verdict={update['debate_verdict']} conf={update.get('debate_confidence')}"
                    elif "trader_decision" in update:
                        detail = f" · action={update['trader_decision'].get('action')}"
                    elif "risk_approved" in update:
                        detail = f" · approved={update['risk_approved']}"
                print(f"  ▸ {node}{detail}", flush=True)
        else:
            final_state = chunk

    pm = final_state.get("pm_decision", {})
    allocations = final_state.get("allocations", [])
    exchange_mode = os.environ.get("EXCHANGE_MODE", "paper")

    # ── Shadow mode (§8.9): persistir las señales hipotéticas del challenger ──
    shadow = final_state.get("shadow_signals", [])
    if shadow:
        from src.brain.shadow import persist_shadow_signals

        n_shadow = persist_shadow_signals(run_id, shadow)
        print(
            f"[shadow] {n_shadow} señales del challenger "
            f"({shadow[0].get('model', '?')}) persistidas — no ejecutan",
            flush=True,
        )

    print(f"\n{'=' * 60}")
    print(f"Run ID  : {run_id}")
    print(
        f"Verdict : {final_state.get('debate_verdict')} "
        f"(conf {final_state.get('debate_confidence', 0):.0%})"
    )
    print(f"Lead    : {pm.get('action')} {pm.get('symbol')} ${pm.get('size_usd', 0):.2f}")
    print(f"Risk    : {'✅ APPROVED' if final_state.get('risk_approved') else '❌ REJECTED'}")

    # ── Ejecución del portafolio (§8.8): el allocator repartió el budget; ejecutamos el vector ──
    budget = float(os.environ.get("HERMES_CAPITAL_USD", "1"))
    active = [a for a in allocations if a.get("action") != "HOLD" and a.get("size_usd", 0) > 0]
    print(
        f"\n[allocator] budget=${budget:.2f} · {len(active)}/{len(allocations)} legs activos · {exchange_mode}"
    )
    for a in allocations:
        print(
            f"  • {a['symbol']:12s} w={a['target_weight']:+.3f} "
            f"target=${a['target_usd']:.4f} → {a['action']} ${a['size_usd']:.4f}"
        )

    if current_positions:
        print(
            "[execution] ⚠️ libro no vacío — el neteo real de rebalanceo requiere upgrade del "
            "PaperAdapter; v1 ejecuta despliegue tipo día-0 (ver docs/DESIGN_portfolio_allocator.md)",
            flush=True,
        )

    order_results: list[dict[str, Any]] = []
    for a in active:
        result = adapter.execute(
            {"action": a["action"], "symbol": a["symbol"], "size_usd": a["size_usd"]},
            run_id,
        )
        print(
            f"[execution] {result.action} {result.symbol} ${a['size_usd']:.4f} "
            f"→ {result.status} qty={result.quantity}"
            + (f" · {result.error}" if result.error else ""),
            flush=True,
        )
        order_results.append(
            {
                "order_id": result.order_id,
                "status": result.status,
                "action": result.action,
                "symbol": result.symbol,
                "quantity": result.quantity,
                "price": result.price,
                "cost_usd": result.cost_usd,
                "fee_usd": result.fee_usd,
                "error": result.error,
            }
        )
    if not active:
        print("[execution] sin legs para ejecutar — freno global o todo HOLD", flush=True)
    final_state["order_results"] = order_results

    positions = adapter.get_positions()
    balance = adapter.get_balance()
    print(f"[execution] {len(positions)} open positions · balance=${balance:.2f}")
    final_state["positions"] = [
        {
            "symbol": p.symbol,
            "action": p.action,
            "quantity": p.quantity,
            "entry_price": p.entry_price,
            "unrealized_pnl": p.unrealized_pnl,
        }
        for p in positions
    ]
    final_state["balance"] = balance

    cost = meter.summary()
    persist_run(meter)
    final_state["cost"] = cost
    print(
        f"[cost] real LLM: ${cost['cost_usd']:.4f} USD · "
        f"{cost['total_tokens']:,} tokens · {cost['n_calls']} llamadas"
    )
    print(
        f"[cost] registrar en ledger:  /cost:log "
        f"llm|{datetime.now(UTC):%Y-%m-%d}|run_id {run_id}|"
        f"{cost['cost_usd']:.4f}|auto"
    )

    print(f"{'=' * 60}")
    print(f"PM rationale: {pm.get('rationale', '')[:300]}")

    return final_state


if __name__ == "__main__":
    import sys

    # `--estimate` prints the pre-run LLM cost estimate and exits (no models
    # invoked) — used by /agents:run to feed /cost:gate BEFORE running.
    if "--estimate" in sys.argv:
        from src.brain.cost_meter import estimate_cost_usd

        print(f"{estimate_cost_usd():.4f}")
    else:
        run()
