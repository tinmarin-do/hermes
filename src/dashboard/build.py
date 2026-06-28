"""dashboard:build — generate src/dashboard/static/data/snapshot.json from the DB.

The dashboard reads this static snapshot so per-visitor cost is $0 (no model
inference or LLM calls on page load). Focus of this build: the SHAP
explainability panel for the quant core, plus a minimal MLOps/cost panel and
open positions. Equity curve / debate viewer are TODO.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT_PATH = Path(__file__).parent / "static" / "data" / "snapshot.json"


def _symbols() -> list[str]:
    raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
    return [s.strip() for s in raw.split(",") if s.strip()]


def _shap_panel(symbols: list[str], timeframe: str) -> dict[str, Any]:
    """Per-symbol SHAP explanation of the latest gold signal."""
    from src.brain.quant_core import QuantCore
    from src.data.gold.aggregate import aggregate

    try:
        core = QuantCore.load()
    except Exception as exc:  # no model trained yet
        return {"available": False, "reason": f"no model: {exc}", "symbols": {}}

    if not core.is_trained():
        return {"available": False, "reason": "model not ready", "symbols": {}}

    signals = aggregate(symbols, timeframe)
    by_symbol: dict[str, Any] = {}
    for sig in signals:
        explanation = core.explain(sig)
        by_symbol[sig["symbol"]] = {
            "ts": sig.get("ts"),
            "regime": sig.get("regime"),
            "explanation": explanation,
        }
    return {"available": True, "symbols": by_symbol}


def _cost_panel() -> dict[str, Any]:
    """LLM spend from llm_cost_runs (measured by src.brain.cost_meter)."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        try:
            row = con.execute(
                "SELECT COALESCE(SUM(cost_usd),0), COUNT(*), "
                "COALESCE(SUM(CASE WHEN NOT logged_to_ledger THEN 1 ELSE 0 END),0) "
                "FROM llm_cost_runs"
            ).fetchone()
            total, n_runs, unlogged = row if row else (0, 0, 0)
            recent = con.execute(
                "SELECT run_id, ts, total_tokens, cost_usd, logged_to_ledger "
                "FROM llm_cost_runs ORDER BY ts DESC LIMIT 10"
            ).fetchall()
        except Exception:
            return {"available": False, "total_usd": 0.0, "runs": 0, "recent": []}
    finally:
        con.close()

    return {
        "available": True,
        "total_usd": round(float(total), 4),
        "runs": int(n_runs),
        "unlogged_runs": int(unlogged),
        "budget_usd": 150.0,
        "recent": [
            {
                "run_id": r[0][:8],
                "ts": str(r[1]),
                "tokens": int(r[2]),
                "cost_usd": round(float(r[3]), 4),
                "logged": bool(r[4]),
            }
            for r in recent
        ],
    }


def _positions_panel() -> dict[str, Any]:
    """Open paper positions + balance."""
    try:
        from src.execution.adapter import PaperAdapter

        pa = PaperAdapter()
        positions = pa.get_positions()
        return {
            "available": True,
            "balance_usd": pa.get_balance(),
            "open": [
                {
                    "symbol": p.symbol,
                    "action": p.action,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in positions
            ],
        }
    except Exception as exc:
        return {"available": False, "reason": str(exc), "open": []}


def build_snapshot(timeframe: str = "1h") -> dict[str, Any]:
    symbols = _symbols()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbols": symbols,
        "timeframe": timeframe,
        "shap": _shap_panel(symbols, timeframe),
        "cost": _cost_panel(),
        "positions": _positions_panel(),
        # TODO: equity curve, trade history, risk metrics (Sharpe/PSR/Sortino),
        # debate transcript viewer — see dashboard:build skill.
    }


def main() -> int:
    snapshot = build_snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))

    shap = snapshot["shap"]
    n_shap = len(shap.get("symbols", {})) if shap.get("available") else 0
    print(f"✅ Snapshot generado → {SNAPSHOT_PATH}")
    print(
        f"   SHAP: {'sí' if shap.get('available') else 'no — ' + shap.get('reason', '')} "
        f"({n_shap} símbolos)"
    )
    print(
        f"   Costo LLM total: ${snapshot['cost'].get('total_usd', 0):.4f} "
        f"({snapshot['cost'].get('runs', 0)} corridas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
