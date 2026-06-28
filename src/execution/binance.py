"""BinanceAdapter — ccxt-powered execution against Binance testnet and live."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import ccxt

from src.execution.adapter import ExecutionAdapter
from src.execution.kill import kill_switch
from src.execution.models import OrderResult, Position
from src.execution.schema import ensure_execution_schema

if TYPE_CHECKING:
    import duckdb


class BinanceAdapter(ExecutionAdapter):
    def __init__(self, mode: str = "testnet") -> None:
        self.mode = mode
        ensure_execution_schema()
        self._exchange = self._build_exchange()

    def _build_exchange(self) -> ccxt.binance:
        if self.mode == "testnet":
            exchange = ccxt.binance({
                "apiKey": os.environ.get("BINANCE_TESTNET_API_KEY", ""),
                "secret": os.environ.get("BINANCE_TESTNET_API_SECRET", ""),
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            exchange.set_sandbox_mode(True)
            exchange.urls["api"] = exchange.urls["test"]
            return exchange
        elif self.mode == "live":
            return ccxt.binance({
                "apiKey": os.environ.get("BINANCE_API_KEY", ""),
                "secret": os.environ.get("BINANCE_API_SECRET", ""),
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
        raise ValueError(f"Unknown mode: {self.mode}")

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

        try:
            ticker = self._exchange.fetch_ticker(symbol)
            price = ticker.get("last") or ticker.get("close")
            if price is None:
                return OrderResult(
                    order_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
                    action=action, quantity=0, status="REJECTED",
                    error=f"No ticker for {symbol}",
                )

            amount = round(size_usd / price, 6)
            min_amount = self._exchange.markets[symbol].get("limits", {}).get("amount", {}).get("min", 0)
            if amount < min_amount:
                return OrderResult(
                    order_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
                    action=action, quantity=amount, status="REJECTED",
                    error=f"Amount {amount} below minimum {min_amount}",
                )

            ccxt_action = action.lower()
            params: dict = {}
            if action == "SELL":
                params["type"] = "market"

            cco = self._exchange.create_order(
                symbol, "market", ccxt_action, amount, None, params,
            )

            filled = float(cco.get("filled", 0) or 0)
            status = "FILLED" if filled > 0 else "REJECTED"
            filled_at = datetime.now(timezone.utc).replace(tzinfo=None)

            self._persist_order(run_id, symbol, action, amount, price, status, filled_at)

            return OrderResult(
                order_id=cco.get("id", str(uuid.uuid4())), run_id=run_id,
                symbol=symbol, action=action, quantity=filled,
                price=price, status=status, filled_at=filled_at,
            )
        except ccxt.BaseError as exc:
            return OrderResult(
                order_id=str(uuid.uuid4()), run_id=run_id, symbol=symbol,
                action=action, quantity=0, status="REJECTED",
                error=str(exc)[:200],
            )

    @staticmethod
    def _persist_order(run_id: str, symbol: str, action: str, quantity: float,
                       price: float, status: str, filled_at: datetime) -> None:
        from src.data.db import get_connection
        con = get_connection()
        try:
            con.execute("""
                INSERT OR REPLACE INTO execution_orders
                    (order_id, run_id, symbol, action, quantity, price, status,
                     filled_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [str(uuid.uuid4()), run_id, symbol, action, quantity, price,
                  status, filled_at, filled_at])
        finally:
            con.close()

    def get_positions(self) -> list[Position]:
        try:
            raw = self._exchange.fetch_positions()
        except Exception:
            raw = []

        positions = []
        for p in raw:
            contracts = float(p.get("contracts", 0) or 0)
            if contracts <= 0:
                continue
            positions.append(Position(
                symbol=p.get("symbol", ""),
                action="BUY" if (p.get("side", "long") == "long") else "SELL",
                quantity=contracts,
                entry_price=float(p.get("entryPrice", 0) or 0),
                unrealized_pnl=float(p.get("unrealizedPnl", 0) or 0),
            ))
        return positions

    def get_balance(self) -> float:
        try:
            bal = self._exchange.fetch_balance()
            return float(bal.get("USDT", {}).get("free", 0))
        except Exception:
            return 0.0

    def kill(self) -> None:
        kill_switch.activate("BinanceAdapter kill called")
        try:
            self._exchange.cancel_all_orders()
        except Exception:
            pass

    def is_alive(self) -> bool:
        return kill_switch.is_alive()
