"""Ejecutor del spread L/S H13 (F7) — reconcilia Binance Futures contra el shadow.

UNA sola fuente de verdad (§10.1): el ejecutor NO re-calcula la señal — lee el
entry más reciente del shadow ledger (emitido 00:20 UTC), toma el libro del
ÚLTIMO rebalanceo de la grilla 28d (⛰️; catch-up natural al entrar a media
grilla) y reconcilia la cuenta contra ese target.

Reglas duras implementadas:
- Budget dinámico = wallet (decisión Erika 2026-07-13).
- Libro completo o CASH: si el balance no alcanza MIN_NOTIONAL en las 10 patas,
  o falta el perp de algún símbolo del libro, NO se arma libro mocho → alerta.
- Margen AISLADO + 1x por símbolo antes de la primera orden.
- Cap por símbolo 15% del wallet. reduceOnly en cierres. Kill switch --kill.
- DRY-RUN por default (EXECUTE=true para órdenes reales — estándar PR #39).

Corre como job (europe-west1):  python -m src.execution.spread_executor
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.execution.binance_futures import (
    MAINNET,
    BinanceFuturesClient,
    round_step,
)
from src.lab import gcs
from src.lab.h13_eval import spread_leg_weights
from src.lab.shadow_producer import GRU_ID, days_prefix
from src.lab.shadow_spread import _sigma20_from_ledger

SPEC_BLOB = "models/h13-gruls-ivol.json"
SPEC_SHA_PREFIX = os.environ.get("H13_SPEC_SHA", "0dac692a")
PER_SYMBOL_CAP = 0.15  # fracción máxima del wallet por pata
MAX_ENTRY_AGE_DAYS = 2
LOG_PREFIX = "executions/h13/"


def to_perp(base_symbol: str) -> str:
    return f"{base_symbol}USDT"


def latest_standing_book_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """El entry del ÚLTIMO rebalanceo de la grilla — ese define el libro vigente."""
    rebs = [e for e in entries if e.get("is_rebalance") and e.get("universe")]
    return max(rebs, key=lambda e: str(e["decision_date"])) if rebs else None


def plumbing_universe(
    entry: dict[str, Any],
    balance: float,
    marks: dict[str, float],
    filters: dict[str, dict[str, float]],
    leg_frac: float = PER_SYMBOL_CAP,
) -> tuple[dict[str, Any], int]:
    """§10.2 SOLO-PLOMERÍA: universo asequible (pata mínima ≤ leg_frac·balance)
    y k adaptativo (min(5, ⌊n/2⌋)). Devuelve (entry filtrado, k)."""
    keep = []
    for u in entry["universe"]:
        perp = to_perp(str(u["symbol"]))
        if perp not in filters or perp not in marks:
            continue
        min_leg = max(filters[perp]["min_notional"], filters[perp]["step_size"] * marks[perp])
        if min_leg <= leg_frac * balance:
            keep.append(u)
    return {**entry, "universe": keep}, min(5, len(keep) // 2)


def build_target_weights(
    entry: dict[str, Any], sigma: dict[str, float], top_k: int, mode: str
) -> dict[str, float]:
    """Pesos firmados {base_symbol: w} del libro vigente (ivol; fallback ew)."""
    day = pd.DataFrame(entry["universe"]).set_index("symbol")
    day["sigma20"] = [sigma.get(str(s), float("nan")) for s in day.index]
    eff = mode if day["sigma20"].notna().all() else "ew"
    w_long, w_short = spread_leg_weights(day, top_k, eff)
    out = {str(s): float(w) for s, w in w_long.items()}
    for s, w in w_short.items():
        out[str(s)] = out.get(str(s), 0.0) - float(w)
    return out


def plan_orders(
    target_w: dict[str, float],
    balance: float,
    marks: dict[str, float],
    positions: dict[str, float],
    filters: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Plan de reconciliación (puro). Devuelve {'orders': [...]} o {'cash': razón}.

    Libro completo o nada: cualquier pata imposible (sin perp, sin mark, bajo el
    MIN_NOTIONAL del venue, o sobre el cap por símbolo) → CASH con razón.
    """
    targets: dict[str, float] = {}  # perp → qty firmada objetivo
    for base, w in target_w.items():
        perp = to_perp(base)
        if perp not in filters:
            return {"cash": f"{perp} sin contrato perpetuo en el venue"}
        if perp not in marks or marks[perp] <= 0:
            return {"cash": f"{perp} sin mark price"}
        notional = abs(w) * balance
        if notional > PER_SYMBOL_CAP * balance + 1e-9:
            return {"cash": f"{perp} excede cap por símbolo ({PER_SYMBOL_CAP:.0%})"}
        qty = round_step(notional / marks[perp], filters[perp]["step_size"])
        if qty * marks[perp] < filters[perp]["min_notional"]:
            return {
                "cash": f"{perp} bajo MIN_NOTIONAL "
                f"({qty * marks[perp]:.2f} < {filters[perp]['min_notional']:.2f} USDT) — "
                "balance insuficiente para el libro completo"
            }
        targets[perp] = qty if w > 0 else -qty

    orders: list[dict[str, Any]] = []
    # cierres primero (posiciones que ya no están en el target o cambian de signo)
    for perp, cur in positions.items():
        tgt = targets.get(perp, 0.0)
        if cur * tgt <= 0 and cur != 0.0:  # fuera del libro o flip de signo
            orders.append(
                {
                    "symbol": perp,
                    "side": "SELL" if cur > 0 else "BUY",
                    "qty": abs(cur),
                    "reduce_only": True,
                }
            )
    # ajustes/entradas después
    for perp, tgt in targets.items():
        cur = positions.get(perp, 0.0)
        base_cur = cur if cur * tgt > 0 else 0.0  # si hubo flip, ya se cerró arriba
        delta = tgt - base_cur
        step = filters[perp]["step_size"]
        if abs(delta) < step:
            continue
        qty = round_step(abs(delta), step)
        if qty <= 0:
            continue
        shrinking = abs(tgt) < abs(base_cur)
        orders.append(
            {
                "symbol": perp,
                "side": "BUY" if delta > 0 else "SELL",
                "qty": qty,
                "reduce_only": bool(shrinking),
            }
        )
    return {"orders": orders, "targets": targets}


def main() -> int:
    ap = argparse.ArgumentParser(description="Ejecutor spread L/S H13")
    ap.add_argument("--kill", action="store_true", help="cierra TODAS las posiciones y sale")
    a = ap.parse_args()

    execute = os.environ.get("EXECUTE", "false").lower() == "true"
    client = BinanceFuturesClient(
        api_key=os.environ["BINANCE_FUTURES_KEY"],
        api_secret=os.environ["BINANCE_FUTURES_SECRET"],
        base=os.environ.get("BINANCE_FUTURES_BASE", MAINNET),
    )
    now = datetime.now(UTC)
    log: dict[str, Any] = {"ts": now.isoformat(), "execute": execute, "kill": a.kill}

    if a.kill:
        positions = client.positions()
        log["closing"] = positions
        for perp, amt in positions.items():
            if execute:
                client.market_order(perp, "SELL" if amt > 0 else "BUY", abs(amt), reduce_only=True)
        print(f"[executor] KILL: {len(positions)} posiciones {'cerradas' if execute else '(dry)'}")
        gcs.upload_json(log, f"{LOG_PREFIX}{now.date()}-kill.json")
        return 0

    spec = json.loads(gcs.bucket().blob(SPEC_BLOB).download_as_text())
    if not spec["sha256"].startswith(SPEC_SHA_PREFIX):
        print(f"ABORT: spec sha {spec['sha256'][:12]} != {SPEC_SHA_PREFIX}")
        return 1

    entries = [
        json.loads(gcs.bucket().blob(b).download_as_text())
        for b in sorted(gcs.list_blobs(days_prefix(GRU_ID)))
    ]
    standing = latest_standing_book_entry(entries)
    if standing is None:
        print("[executor] sin rebalanceo en el ledger — CASH")
        return 1
    age = (now.date() - pd.Timestamp(str(entries[-1]["decision_date"])).date()).days
    if age > MAX_ENTRY_AGE_DAYS:
        log["cash"] = f"ledger viejo ({age}d sin emisión) — shadow caído?"
        gcs.upload_json(log, f"{LOG_PREFIX}{now.date()}.json")
        print(f"[executor] ALERTA: {log['cash']}")
        return 1

    sigma = _sigma20_from_ledger(entries, str(standing["decision_date"]))
    balance = client.balance_usdt()
    marks, filters = client.mark_prices(), client.exchange_filters()
    plumbing = os.environ.get("PLUMBING_MODE", "false").lower() == "true"
    if plumbing:
        # §10.2: mecánica con libro reducido asequible — EW forzado, gross 0.9
        book_entry, k = plumbing_universe(standing, balance, marks, filters)
        log["plumbing_mode"] = {"k": k, "universe": [u["symbol"] for u in book_entry["universe"]]}
        if k < 3:
            log["cash"] = f"plomería: solo {k * 2} patas asequibles (mínimo 3+3) — CASH"
            gcs.upload_json(log, f"{LOG_PREFIX}{now.date()}.json")
            print(f"[executor] {log['cash']}")
            return 1
        target_w = {s: w * 0.9 for s, w in build_target_weights(book_entry, sigma, k, "ew").items()}
    else:
        target_w = build_target_weights(
            standing, sigma, int(spec["top_k"]), str(spec["leg_weighting"])
        )
    plan = plan_orders(target_w, balance, marks, client.positions(), filters)
    log.update(
        {
            "standing_book_date": standing["decision_date"],
            "balance_usdt": balance,
            "target_weights": target_w,
            "plan": plan,
        }
    )

    if "cash" in plan:
        print(f"[executor] CASH: {plan['cash']}")
    else:
        for o in plan["orders"]:
            if execute:
                client.ensure_isolated_1x(o["symbol"])
                r = client.market_order(o["symbol"], o["side"], o["qty"], o["reduce_only"])
                o["order_id"] = r.get("orderId")
            print(
                f"[executor] {'ORDEN' if execute else 'DRY'} {o['side']} {o['qty']} "
                f"{o['symbol']}{' reduceOnly' if o['reduce_only'] else ''}"
            )
        print(
            f"[executor] libro {standing['decision_date']} · balance {balance:.2f} USDT · "
            f"{len(plan['orders'])} órdenes {'ejecutadas' if execute else 'planeadas (dry-run)'}"
        )
    gcs.upload_json(log, f"{LOG_PREFIX}{now.date()}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
