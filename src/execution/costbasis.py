"""Cost basis desde execution_orders — fix hallazgo G (diagnóstico 2026-07-07).

El BitsoAdapter reporta tenencias spot con entry_price = precio actual (el venue
no guarda "mi costo"), así que el dashboard mostraba P&L $0 POR DISEÑO. La verdad
histórica sí existe: cada fill (paper, testnet o live) queda en `execution_orders`
con cost_usd y fee_usd. Este módulo la reconstruye con **costo promedio**:

- BUY  FILLED: suma qty y basis (cost_usd, sin fee — los fees se reportan aparte).
- SELL FILLED: realiza P&L = proceeds − avg_cost × qty_vendida y descuenta basis.
- Un SELL mayor a la qty trackeada se recorta a lo trackeado (monedas depositadas
  fuera de Hermes no tienen costo conocido — no se les inventa P&L).

P&L neto honesto = realized + unrealized − fees. El unrealized lo calcula el
consumidor con el precio vivo: (precio − avg_cost) × min(qty_wallet, qty_trackeada).
"""

from __future__ import annotations


def cost_basis(symbols: list[str] | None = None) -> dict[str, dict[str, float]]:
    """Reconstruye el costo promedio por símbolo desde los fills persistidos.

    Devuelve {symbol: {qty, avg_cost, basis_usd, realized_pnl, fees_usd, n_fills}}.
    Solo órdenes FILLED, en orden cronológico (el promedio depende del orden).
    """
    from src.data.db import get_connection

    con = get_connection()
    try:
        rows = con.execute(
            "SELECT symbol, action, quantity, cost_usd, fee_usd "
            "FROM execution_orders WHERE status='FILLED' AND quantity > 0 "
            "ORDER BY filled_at, created_at"
        ).fetchall()
    except Exception:
        return {}
    finally:
        con.close()

    book: dict[str, dict[str, float]] = {}
    for symbol, action, qty, cost_usd, fee_usd in rows:
        if symbols is not None and symbol not in symbols:
            continue
        b = book.setdefault(
            symbol,
            {"qty": 0.0, "basis_usd": 0.0, "realized_pnl": 0.0, "fees_usd": 0.0, "n_fills": 0},
        )
        qty = float(qty or 0)
        cost_usd = float(cost_usd or 0)
        b["fees_usd"] += float(fee_usd or 0)
        b["n_fills"] += 1
        if action == "BUY":
            b["qty"] += qty
            b["basis_usd"] += cost_usd
        elif action == "SELL":
            tracked = min(qty, b["qty"])
            if tracked <= 0:
                continue
            avg = b["basis_usd"] / b["qty"] if b["qty"] > 0 else 0.0
            # proceeds proporcionales a la parte trackeada del SELL
            proceeds = cost_usd * (tracked / qty) if qty > 0 else 0.0
            b["realized_pnl"] += proceeds - avg * tracked
            b["basis_usd"] -= avg * tracked
            b["qty"] -= tracked

    for b in book.values():
        b["avg_cost"] = b["basis_usd"] / b["qty"] if b["qty"] > 1e-12 else 0.0
        for k in ("qty", "avg_cost", "basis_usd", "realized_pnl", "fees_usd"):
            b[k] = round(b[k], 8)
    return book
