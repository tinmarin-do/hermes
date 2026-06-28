"""Entry point for one pipeline run — brain → execution."""
import os
import uuid
from datetime import datetime, timezone

from src.brain.graph import hermes_graph
from src.data.gold.aggregate import aggregate


def _get_adapter():
    exchange_mode = os.environ.get("EXCHANGE_MODE", "paper")
    if exchange_mode == "live":
        from src.execution.binance import BinanceAdapter
        return BinanceAdapter(mode="live")
    elif exchange_mode == "testnet":
        from src.execution.binance import BinanceAdapter
        return BinanceAdapter(mode="testnet")
    else:
        from src.execution.adapter import PaperAdapter
        return PaperAdapter()


def run(symbols: list[str] | None = None, timeframe: str = "1h") -> dict:
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
    print(f"[cost] estimado LLM de esta corrida: ~${est:.4f} USD "
          f"(autorizar via /cost:gate antes de corridas programadas)", flush=True)

    initial_state: dict = {
        "run_id": run_id,
        "symbols": symbols,
        "timeframe": timeframe,
        "gold_signals": gold_signals,
        "regime_summary": "",
        "quant_signal": {},
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
    final_state: dict = initial_state
    for mode, chunk in hermes_graph.stream(initial_state, stream_mode=["updates", "values"]):
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
    print(f"\n{'='*60}")
    print(f"Run ID  : {run_id}")
    print(f"Verdict : {final_state.get('debate_verdict')} "
          f"(conf {final_state.get('debate_confidence', 0):.0%})")
    print(f"Decision: {pm.get('action')} {pm.get('symbol')} ${pm.get('size_usd', 0):.2f}")
    print(f"Risk    : {'✅ APPROVED' if final_state.get('risk_approved') else '❌ REJECTED'}")

    approved = final_state.get("risk_approved", False)
    adapter = _get_adapter()
    exchange_mode = os.environ.get("EXCHANGE_MODE", "paper")

    if approved and pm.get("action", "HOLD") != "HOLD":
        print(f"\n[execution] sending order via {exchange_mode} adapter", flush=True)
        result = adapter.execute(pm, run_id)
        print(f"[execution] order_id={result.order_id} status={result.status} "
              f"{result.symbol} {result.action} qty={result.quantity} "
              f"price={result.price} cost=${result.cost_usd:.2f}", flush=True)
        if result.error:
            print(f"[execution] error: {result.error}", flush=True)
        final_state["order_result"] = {
            "order_id": result.order_id, "status": result.status,
            "action": result.action, "symbol": result.symbol,
            "quantity": result.quantity, "price": result.price,
            "cost_usd": result.cost_usd, "fee_usd": result.fee_usd,
            "error": result.error,
        }
    else:
        print(f"[execution] no order — approved={approved}, action={pm.get('action', 'HOLD')}", flush=True)
        final_state["order_result"] = None

    positions = adapter.get_positions()
    balance = adapter.get_balance()
    print(f"[execution] {len(positions)} open positions · balance=${balance:.2f}")
    final_state["positions"] = [{
        "symbol": p.symbol, "action": p.action, "quantity": p.quantity,
        "entry_price": p.entry_price, "unrealized_pnl": p.unrealized_pnl,
    } for p in positions]
    final_state["balance"] = balance

    cost = meter.summary()
    persist_run(meter)
    final_state["cost"] = cost
    print(f"[cost] real LLM: ${cost['cost_usd']:.4f} USD · "
          f"{cost['total_tokens']:,} tokens · {cost['n_calls']} llamadas")
    print(f"[cost] registrar en ledger:  /cost:log "
          f"llm|{datetime.now(timezone.utc):%Y-%m-%d}|run_id {run_id}|"
          f"{cost['cost_usd']:.4f}|auto")

    print(f"{'='*60}")
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
