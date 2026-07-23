"""ExecutionAdapter — abstract base + PaperAdapter (simulated execution)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.data.db import get_connection
from src.execution.kill import kill_switch
from src.execution.models import OrderResult, Position
from src.execution.schema import ensure_execution_schema

if TYPE_CHECKING:
    pass


class ExecutionAdapter(ABC):
    """Agents send decisions here. The adapter executes against paper/testnet/live."""

    @abstractmethod
    def execute(self, decision: dict[str, Any], run_id: str) -> OrderResult:
        """Execute a trading decision. Returns an OrderResult."""
        ...

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Return all currently open positions."""
        ...

    @abstractmethod
    def get_balance(self) -> float:
        """Return available cash balance."""
        ...

    def get_equity(self) -> float:
        """Cash + mark-to-market del libro. Default: solo caja (adapters sin libro)."""
        return self.get_balance()

    @abstractmethod
    def kill(self) -> None:
        """Emergency stop — cancel everything, close all positions if possible."""
        ...

    @abstractmethod
    def is_alive(self) -> bool:
        """Check if the kill switch has NOT been activated."""
        ...


class PaperAdapter(ExecutionAdapter):
    """Simulated execution against DuckDB — no real exchange, free backtesting.

    Uses the current market price from bronze_ohlcv for fills. Tracks NET positions
    per symbol in execution_positions (§8.8 rebalanceo): an incoming order first
    reduces/closes the opposite side (booking realized P&L and recycling cash) and
    only the remainder opens or extends its own side (weighted-average entry).

    Cash model: BUY = cash out (size + fee) · SELL = cash in (size − fee). Los
    proceeds de un short simulado acreditan caja sin margen real — distorsión
    aceptable en paper con el cap corto del 10% (§8.8); testnet/live usan venue real.
    """

    def __init__(self, initial_balance: float = 1.0) -> None:
        self.initial_balance = initial_balance
        ensure_execution_schema()

    @staticmethod
    def _current_price(symbol: str) -> float | None:
        con = get_connection()
        try:
            row = con.execute(
                "SELECT close FROM bronze_ohlcv WHERE symbol = ? ORDER BY ts DESC LIMIT 1",
                [symbol],
            ).fetchone()
            return float(row[0]) if row else None
        finally:
            con.close()

    def execute(self, decision: dict[str, Any], run_id: str) -> OrderResult:
        if not kill_switch.is_alive():
            return OrderResult(
                order_id="",
                run_id=run_id,
                symbol=decision.get("symbol", ""),
                action=decision.get("action", "HOLD"),
                quantity=0,
                status="REJECTED",
                error="Kill switch active — trading halted",
            )

        action = decision.get("action", "HOLD")
        symbol = decision.get("symbol", "NONE")
        size_usd = float(decision.get("size_usd", 0))

        if action == "HOLD" or symbol == "NONE" or size_usd <= 0:
            return OrderResult(
                order_id=str(uuid.uuid4()),
                run_id=run_id,
                symbol=symbol,
                action=action,
                quantity=0,
                status="CANCELLED",
                error="HOLD or zero size — no order placed",
            )

        price = self._current_price(symbol)
        if price is None or price <= 0:
            return OrderResult(
                order_id=str(uuid.uuid4()),
                run_id=run_id,
                symbol=symbol,
                action=action,
                quantity=0,
                status="REJECTED",
                error=f"No price data for {symbol}",
            )

        quantity = round(size_usd / price, 6)
        fee = round(size_usd * 0.001, 2)  # 0.1% simulated fee (redondea a $0 a escala $1)

        # BUY saca caja → check de balance. SELL entra caja (reduce exposición o
        # abre short simulado; los caps de exposición viven en el allocator, §8.8).
        if action == "BUY":
            cost = size_usd + fee
            balance = self.get_balance()
            if cost > balance:
                return OrderResult(
                    order_id=str(uuid.uuid4()),
                    run_id=run_id,
                    symbol=symbol,
                    action=action,
                    quantity=0,
                    status="REJECTED",
                    error=f"Insufficient balance: ${balance:.2f} < ${cost:.2f}",
                )
        else:
            cost = size_usd - fee  # proceeds netos de la venta

        order_id = str(uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)

        con = get_connection()
        try:
            con.execute(
                """
                INSERT INTO execution_orders
                    (order_id, run_id, symbol, action, quantity, price, status,
                     filled_at, created_at, cost_usd, fee_usd)
                VALUES (?, ?, ?, ?, ?, ?, 'FILLED', ?, ?, ?, ?)
            """,
                [order_id, run_id, symbol, action, quantity, price, now, now, cost, fee],
            )
            self._net_into_positions(con, symbol, action, quantity, price, run_id, now)
        finally:
            con.close()

        return OrderResult(
            order_id=order_id,
            run_id=run_id,
            symbol=symbol,
            action=action,
            quantity=quantity,
            price=price,
            status="FILLED",
            filled_at=now,
            cost_usd=cost,
            fee_usd=fee,
        )

    @staticmethod
    def _net_into_positions(
        con: Any,
        symbol: str,
        action: str,
        quantity: float,
        price: float,
        run_id: str,
        now: datetime,
    ) -> None:
        """Neteo (§8.8): reducir primero el lado opuesto (P&L realizado), luego el propio.

        Invariante resultante: a lo sumo UNA posición OPEN por símbolo. Reducciones
        parciales acumulan `realized_pnl` en la fila; al llegar a 0 se cierra con
        `exit_price`. El remanente extiende la posición propia con entry promedio
        ponderado, o abre una nueva.
        """
        opposite = "SELL" if action == "BUY" else "BUY"
        remaining = quantity

        rows = con.execute(
            """SELECT id, quantity, entry_price, COALESCE(realized_pnl, 0)
               FROM execution_positions
               WHERE symbol = ? AND action = ? AND status = 'OPEN' ORDER BY opened_at""",
            [symbol, opposite],
        ).fetchall()
        for pid, pqty, entry, prealized in rows:
            if remaining <= 1e-9:
                break
            matched = min(pqty, remaining)
            # cerrar un largo con SELL gana si px subió; cubrir un short con BUY, si bajó
            pnl = (price - entry) * matched if opposite == "BUY" else (entry - price) * matched
            new_realized = round(prealized + pnl, 4)
            leftover = round(pqty - matched, 6)
            if leftover <= 1e-9:
                con.execute(
                    """UPDATE execution_positions
                       SET closed_at = ?, exit_price = ?, realized_pnl = ?, status = 'CLOSED'
                       WHERE id = ?""",
                    [now, price, new_realized, pid],
                )
            else:
                con.execute(
                    "UPDATE execution_positions SET quantity = ?, realized_pnl = ? WHERE id = ?",
                    [leftover, new_realized, pid],
                )
            remaining = round(remaining - matched, 6)

        if remaining > 1e-9:
            own = con.execute(
                """SELECT id, quantity, entry_price FROM execution_positions
                   WHERE symbol = ? AND action = ? AND status = 'OPEN' ORDER BY opened_at""",
                [symbol, action],
            ).fetchone()
            if own:
                pid, oqty, oentry = own
                total = round(oqty + remaining, 6)
                avg_entry = (oqty * oentry + remaining * price) / total
                con.execute(
                    "UPDATE execution_positions SET quantity = ?, entry_price = ? WHERE id = ?",
                    [total, round(avg_entry, 6), pid],
                )
            else:
                con.execute(
                    """INSERT INTO execution_positions
                        (symbol, action, quantity, entry_price, opened_at, run_id, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'OPEN')""",
                    [symbol, action, remaining, price, now, run_id],
                )

    def get_positions(self) -> list[Position]:
        con = get_connection()
        try:
            rows = con.execute("""
                SELECT id, symbol, action, quantity, entry_price, opened_at,
                       closed_at, exit_price, realized_pnl, run_id, status
                FROM execution_positions WHERE status = 'OPEN'
                ORDER BY opened_at
            """).fetchall()
        finally:
            con.close()

        positions = []
        for r in rows:
            current = self._current_price(r[1])
            entry = r[4]
            qty = r[3]
            unrealized = 0.0
            if current and entry:
                if r[2] == "BUY":
                    unrealized = round((current - entry) * qty, 4)
                else:
                    unrealized = round((entry - current) * qty, 4)

            positions.append(
                Position(
                    id=r[0],
                    symbol=r[1],
                    action=r[2],
                    quantity=qty,
                    entry_price=entry,
                    current_price=current,
                    unrealized_pnl=unrealized,
                    realized_pnl=r[8] or 0,
                    opened_at=r[5],
                    closed_at=r[6],
                    run_id=r[9],
                    status=r[10],
                )
            )
        return positions

    def get_balance(self) -> float:
        """Caja disponible: BUY resta (cash out), SELL suma (proceeds)."""
        con = get_connection()
        try:
            row = con.execute("""
                SELECT COALESCE(SUM(CASE WHEN action = 'BUY' THEN cost_usd
                                         ELSE -cost_usd END), 0)
                FROM execution_orders WHERE status = 'FILLED'
            """).fetchone()
            net_out = float(row[0]) if row else 0
        finally:
            con.close()
        return round(self.initial_balance - net_out, 4)

    def get_equity(self) -> float:
        """Equity total = caja + valor de mercado firmado del libro (longs +, shorts −)."""
        equity = self.get_balance()
        for p in self.get_positions():
            px = p.current_price or p.entry_price
            mv = p.quantity * px
            equity += mv if p.action == "BUY" else -mv
        return round(equity, 4)

    def kill(self) -> None:
        kill_switch.activate("PaperAdapter kill called")
        self._close_all_positions()

    def is_alive(self) -> bool:
        return kill_switch.is_alive()

    def _close_all_positions(self) -> None:
        """Liquidación (kill switch): cierra cada posición e inserta la orden de
        cierre correspondiente para que la caja quede coherente con el neteo."""
        con = get_connection()
        try:
            positions = self.get_positions()
            now = datetime.now(UTC).replace(tzinfo=None)
            for p in positions:
                current = self._current_price(p.symbol)
                exit_price = current or p.entry_price
                size_usd = round(p.quantity * exit_price, 4)
                fee = round(size_usd * 0.001, 2)
                if p.action == "BUY":
                    pnl = (exit_price - p.entry_price) * p.quantity
                    close_action, cost = "SELL", size_usd - fee  # vender el largo → entra caja
                else:
                    pnl = (p.entry_price - exit_price) * p.quantity
                    close_action, cost = "BUY", size_usd + fee  # cubrir el short → sale caja
                con.execute(
                    """
                    INSERT INTO execution_orders
                        (order_id, run_id, symbol, action, quantity, price, status,
                         filled_at, created_at, cost_usd, fee_usd)
                    VALUES (?, 'kill-switch', ?, ?, ?, ?, 'FILLED', ?, ?, ?, ?)
                """,
                    [
                        str(uuid.uuid4()),
                        p.symbol,
                        close_action,
                        p.quantity,
                        exit_price,
                        now,
                        now,
                        cost,
                        fee,
                    ],
                )
                con.execute(
                    """
                    UPDATE execution_positions
                    SET closed_at = ?, exit_price = ?, realized_pnl = ?, status = 'CLOSED'
                    WHERE id = ?
                """,
                    [now, exit_price, round((p.realized_pnl or 0) + pnl, 4), p.id],
                )
        finally:
            con.close()
