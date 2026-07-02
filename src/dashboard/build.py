"""dashboard:build — generate src/dashboard/static/data/snapshot.json from the DB.

The dashboard reads this static snapshot so per-visitor cost is $0 (no model
inference or LLM calls on page load). Panels (PRD v0.3 §5.4, Fase 3):
cartera (pesos actuales vs objetivo cuant, P&L, caja/equity) · equity curve +
métricas honestas (PSR/Sharpe/maxDD sólo con muestra suficiente) · champion vs
shadow (signal log §8.9) · visor de debate (run_transcripts) · SHAP del
challenger · costo LLM · posiciones.
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
        "budget_usd": float(os.environ.get("LLM_MONTHLY_CAP_USD", "150")),
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


def _portfolio_panel(timeframe: str) -> dict[str, Any]:
    """Cartera: pesos actuales vs objetivo cuant (pre-freno LLM), P&L, caja y equity."""
    try:
        from src.execution.adapter import PaperAdapter

        budget = float(os.environ.get("HERMES_CAPITAL_USD", "1"))
        pa = PaperAdapter(initial_balance=budget)
        positions = pa.get_positions()
        balance = pa.get_balance()
        equity = pa.get_equity()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}

    # Objetivo cuant ACTUAL: la regla champion sobre el último Gold, normalizada por
    # el allocator con global_mult=1.0 (pre-freno LLM). Determinista, $0.
    targets: dict[str, float] = {}
    champion_now: dict[str, dict[str, Any]] = {}
    try:
        from src.brain.agents.allocator import compute_allocations
        from src.brain.agents.quant import SHORT_MIN_CONF, _short_confirmed
        from src.brain.quant_rule import multiscale_signal
        from src.data.gold.aggregate import aggregate

        gold = aggregate(_symbols(), timeframe)
        qsigs = []
        for g in gold:
            qs = multiscale_signal(g)
            direction, confidence = qs.direction, qs.confidence
            # mismo gate de short del nodo quant (§8.8) — el panel refleja la señal REAL
            if direction == "SELL" and (confidence < SHORT_MIN_CONF or not _short_confirmed(g)):
                direction, confidence = "HOLD", 0.0
            qsigs.append(
                {
                    "symbol": qs.symbol,
                    "direction": direction,
                    "confidence": confidence,
                    "garch_vol": g.get("features", {}).get("garch_vol") or 0.0,
                }
            )
            champion_now[qs.symbol] = {
                "direction": direction,
                "confidence": confidence,
                "momentum": qs.features_used,  # mom_168h/336h/720h/2160h (votos de la regla)
            }
        book = [
            {
                "symbol": p.symbol,
                "action": p.action,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
            }
            for p in positions
        ]
        legs = compute_allocations(qsigs, book, budget=budget, global_mult=1.0)
        targets = {leg["symbol"]: leg["target_weight"] for leg in legs}
    except Exception as exc:  # noqa: S110 — sin Gold/bronze el panel muestra solo el libro
        print(f"[dashboard] objetivo cuant no disponible: {exc}")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in positions:
        px = p.current_price or p.entry_price
        signed_mv = p.quantity * px * (1 if p.action == "BUY" else -1)
        seen.add(p.symbol)
        rows.append(
            {
                "symbol": p.symbol,
                "side": p.action,
                "market_value_usd": round(signed_mv, 4),
                "weight": round(signed_mv / equity, 4) if equity else 0.0,
                "target_weight": targets.get(p.symbol),
                "unrealized_pnl": p.unrealized_pnl,
                "realized_pnl": p.realized_pnl,
            }
        )
    for sym, tw in targets.items():
        if sym not in seen and abs(tw) > 0:
            rows.append(
                {
                    "symbol": sym,
                    "side": "—",
                    "market_value_usd": 0.0,
                    "weight": 0.0,
                    "target_weight": tw,
                    "unrealized_pnl": 0.0,
                    "realized_pnl": 0.0,
                }
            )
    rows.sort(key=lambda r: str(r["symbol"]))

    return {
        "available": True,
        "budget_usd": budget,
        "balance_usd": balance,
        "equity_usd": equity,
        "cash_weight": round(balance / equity, 4) if equity else 1.0,
        "rows": rows,
        "champion_now": champion_now,
        "note": "pesos objetivo = regla momentum multi-escala pre-freno LLM (global_mult=1)",
    }


def _equity_panel(portfolio: dict[str, Any]) -> dict[str, Any]:
    """Serie de equity (un punto por snapshot) + métricas honestas (§3.2 del PRD)."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS equity_curve (
                   ts TIMESTAMP NOT NULL, balance DOUBLE, equity DOUBLE)"""
        )
        if portfolio.get("available"):
            con.execute(
                "INSERT INTO equity_curve VALUES (?, ?, ?)",
                [
                    datetime.now(UTC).replace(tzinfo=None),
                    portfolio.get("balance_usd"),
                    portfolio.get("equity_usd"),
                ],
            )
        series = con.execute("SELECT ts, equity FROM equity_curve ORDER BY ts").fetchall()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    finally:
        con.close()

    equities: list[float] = [round(float(r[1]), 4) for r in series]
    points = [{"ts": str(r[0]), "equity": eq} for r, eq in zip(series, equities, strict=True)]
    metrics: dict[str, Any] | None = None
    note = None
    if len(equities) >= 2:
        from src.brain.backtest import max_drawdown, psr, sharpe_ratio

        returns = [
            equities[i] / equities[i - 1] - 1.0
            for i in range(1, len(equities))
            if equities[i - 1] > 0
        ]
        metrics = {
            "n_points": len(equities),
            "total_return": round(equities[-1] / equities[0] - 1.0, 4) if equities[0] else None,
            "max_drawdown": round(max_drawdown(equities), 4),
        }
        if len(returns) >= 8:
            metrics["sharpe"] = round(sharpe_ratio(returns), 4)
            metrics["psr"] = round(psr(returns), 4)
        else:
            note = f"Sharpe/PSR requieren más muestra (n={len(returns)} retornos < 8) — §3.2"
    else:
        note = "El track record arranca acá: la curva crece con cada corrida/snapshot."

    return {"available": True, "series": points, "metrics": metrics, "note": note}


def _signals_panel(champion_now: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Champion vs shadow (§8.9): última corrida del challenger vs la regla actual."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        tables = [t[0] for t in con.execute("SHOW TABLES").fetchall()]
        if "shadow_signals" not in tables:
            return {"available": False, "reason": "sin signal log todavía", "rows": []}
        latest = con.execute(
            """SELECT run_id, model, max(created_at) AS c FROM shadow_signals
               WHERE model != 'champion-multimom'
               GROUP BY run_id, model ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        shadow_rows: list[Any] = []
        shadow_model = None
        shadow_run = None
        if latest:
            shadow_run, shadow_model = latest[0], latest[1]
            shadow_rows = con.execute(
                """SELECT symbol, direction, confidence, raw_probability
                   FROM shadow_signals WHERE run_id = ? AND model = ? ORDER BY symbol""",
                [shadow_run, shadow_model],
            ).fetchall()
        history = con.execute(
            "SELECT model, COUNT(DISTINCT run_id), COUNT(*) FROM shadow_signals GROUP BY model"
        ).fetchall()
    except Exception as exc:
        return {"available": False, "reason": str(exc), "rows": []}
    finally:
        con.close()

    rows = []
    for sym, direction, conf, prob in shadow_rows:
        champ = champion_now.get(sym, {})
        rows.append(
            {
                "symbol": sym,
                "champion": {
                    "direction": champ.get("direction", "?"),
                    "confidence": champ.get("confidence"),
                },
                "shadow": {"direction": direction, "confidence": conf, "probability": prob},
                "agree": champ.get("direction") == direction,
            }
        )
    return {
        "available": True,
        "shadow_model": shadow_model,
        "shadow_run": (shadow_run or "")[:8],
        "rows": rows,
        "history": [{"model": h[0], "runs": int(h[1]), "signals": int(h[2])} for h in history],
        "note": "el shadow persiste señales hipotéticas y JAMÁS ejecuta (§8.9)",
    }


def _debate_panel() -> dict[str, Any]:
    """Visor de debate: última transcripción persistida por el runner."""
    try:
        from src.brain.transcript import latest_transcript

        latest = latest_transcript()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}
    if latest is None:
        return {"available": False, "reason": "sin corridas persistidas todavía"}
    latest["available"] = True
    return latest


def build_snapshot(timeframe: str = "1h") -> dict[str, Any]:
    symbols = _symbols()
    portfolio = _portfolio_panel(timeframe)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "symbols": symbols,
        "timeframe": timeframe,
        "portfolio": portfolio,
        "equity": _equity_panel(portfolio),
        "signals": _signals_panel(portfolio.get("champion_now", {})),
        "debate": _debate_panel(),
        "shap": _shap_panel(symbols, timeframe),
        "cost": _cost_panel(),
        "positions": _positions_panel(),
    }


def main() -> int:
    snapshot = build_snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))

    shap = snapshot["shap"]
    n_shap = len(shap.get("symbols", {})) if shap.get("available") else 0
    pf = snapshot["portfolio"]
    eq = snapshot["equity"]
    print(f"✅ Snapshot generado → {SNAPSHOT_PATH}")
    if pf.get("available"):
        print(
            f"   Cartera: equity ${pf['equity_usd']:.4f} · cash ${pf['balance_usd']:.4f} "
            f"· {len(pf['rows'])} símbolos"
        )
    print(f"   Equity curve: {len(eq.get('series', []))} puntos")
    print(f"   Champion vs shadow: {len(snapshot['signals'].get('rows', []))} símbolos comparados")
    print(f"   Debate: {'sí' if snapshot['debate'].get('available') else 'sin corridas'}")
    print(f"   SHAP (challenger): {'sí' if shap.get('available') else 'no'} ({n_shap} símbolos)")
    print(
        f"   Costo LLM total: ${snapshot['cost'].get('total_usd', 0):.4f} "
        f"({snapshot['cost'].get('runs', 0)} corridas)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
