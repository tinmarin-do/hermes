"""Execution domain models — OrderResult and Position."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class OrderResult:
    order_id: str
    run_id: str
    symbol: str
    action: str  # BUY | SELL
    quantity: float
    price: float | None = None
    status: str = "PENDING"  # FILLED | REJECTED | CANCELLED
    filled_at: datetime | None = None
    error: str | None = None
    cost_usd: float = 0.0
    fee_usd: float = 0.0


@dataclass
class Position:
    id: int | None = None
    symbol: str = ""
    action: str = "BUY"  # BUY (long) | SELL (short)
    quantity: float = 0.0
    entry_price: float = 0.0
    current_price: float | None = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    run_id: str = ""
    status: str = "OPEN"  # OPEN | CLOSED
