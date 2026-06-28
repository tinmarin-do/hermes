"""ExecutionAdapter — abstract base + PaperAdapter (simulated execution)."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.data.db import get_connection
from src.execution.kill import kill_switch
from src.execution.models import OrderResult, Position
from src.execution.schema import ensure_execution_schema

if TYPE_CHECKING:
    import duckdb


class ExecutionAdapter(ABC):
    """Agents send decisions here. The adapter executes against paper/testnet/live."""

    @abstractmethod
    def execute(self, decision: dict, run_id: str) -> OrderResult:
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

    Uses the current market price from bronze_ohlcv for fills.
    Tracks positions and P&L in execution_positions table.
    """

    def __init__(self, initial_balance: float = 500.0) -> None:
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

    def execute(self, decision: dict, run_id: str) -> OrderResult:
        if not kill_switch.is_alive():
            return OrderResult(
                order_id="", run_id=run_id, symbol=decision.get("symbol", ""),
                action=decision.get("action", "HOLD"), quantity=0,
                status="REJECTED", error="Kill switch active — trading halted",
            )

        action = decision.get("action", "HOLD")
        symbol = decision.get("symbol", "NONE")
        size_usd = float(decision.get("size_usd", 0))

        if action == "HOLD" or symbol == "NONE" or size_usd <= 0:
            return OrderResult(
                order_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
                action=action, quantity=0, status="CANCELLED",
                error="HOLD or zero size — no order placed",
            )

        price = self._current_price(symbol)
        if price is None or price <= 0:
            return OrderResult(
                order_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
                action=action, quantity=0, status="REJECTED",
                error=f"No price data for {symbol}",
            )

        quantity = round(size_usd / price, 6)
        fee = round(size_usd * 0.001, 2)  # 0.1% simulated fee
        cost = size_usd + fee

        balance = self.get_balance()
        if cost > balance:
            return OrderResult(
                order_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
                action=action, quantity=0, status="REJECTED",
                error=f"Insufficient balance: ${balance:.2f} < ${cost:.2f}",
            )

        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        con = get_connection()
        try:
            con.execute("""
                INSERT INTO execution_orders
                    (order_id, run_id, symbol, action, quantity, price, status,
                     filled_at, created_at, cost_usd, fee_usd)
                VALUES (?, ?, ?, ?, ?, ?, 'FILLED', ?, ?, ?, ?)
            """, [order_id, run_id, symbol, action, quantity, price, now, now, cost, fee])

            con.execute("""
                INSERT INTO execution_positions
                    (symbol, action, quantity, entry_price, opened_at, run_id, status)
                VALUES (?, ?, ?, ?, ?, ?, 'OPEN')
            """, [symbol, action, quantity, price, now, run_id])
        finally:
            con.close()

        return OrderResult(
            order_id=order_id, run_id=run_id, symbol=symbol,
            action=action, quantity=quantity, price=price,
            status="FILLED", filled_at=now, cost_usd=cost, fee_usd=fee,
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
                    unrealized = round((current - entry) * qty, 2)
                else:
                    unrealized = round((entry - current) * qty, 2)

            positions.append(Position(
                id=r[0], symbol=r[1], action=r[2], quantity=qty,
                entry_price=entry, current_price=current,
                unrealized_pnl=unrealized, realized_pnl=r[8] or 0,
                opened_at=r[5], closed_at=r[6], run_id=r[9], status=r[10],
            ))
        return positions

    def get_balance(self) -> float:
        con = get_connection()
        try:
            row = con.execute("""
                SELECT COALESCE(SUM(cost_usd), 0) FROM execution_orders
                WHERE status = 'FILLED'
            """).fetchone()
            spent = float(row[0]) if row else 0
        finally:
            con.close()
        return round(self.initial_balance - spent, 2)

    def kill(self) -> None:
        kill_switch.activate("PaperAdapter kill called")
        self._close_all_positions()

    def is_alive(self) -> bool:
        return kill_switch.is_alive()

    def _close_all_positions(self) -> None:
        con = get_connection()
        try:
            positions = self.get_positions()
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for p in positions:
                current = self._current_price(p.symbol)
                exit_price = current or p.entry_price
                pnl = 0.0
                if p.action == "BUY":
                    pnl = (exit_price - p.entry_price) * p.quantity
                else:
                    pnl = (p.entry_price - exit_price) * p.quantity
                con.execute("""
                    UPDATE execution_positions
                    SET closed_at = ?, exit_price = ?, realized_pnl = ?, status = 'CLOSED'
                    WHERE id = ?
                """, [now, exit_price, round(pnl, 2), p.id])
        finally:
            con.close()
