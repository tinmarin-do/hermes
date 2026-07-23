"""Selección del ExecutionAdapter según entorno — runner y dashboard comparten.

Imports lazy a propósito: el dashboard local no debe cargar ccxt/BitsoAdapter
si corre en paper, y el factory jamás jala el grafo LangGraph.
"""

from __future__ import annotations

import os

from src.execution.adapter import ExecutionAdapter


def exchange_mode() -> str:
    return os.environ.get("EXCHANGE_MODE", "paper")


def exchange_label() -> str:
    """Etiqueta honesta para UI: 'live · bitso', 'testnet · binance', 'paper'."""
    mode = exchange_mode()
    if mode == "live":
        return f"live · {os.environ.get('EXCHANGE_ID', 'bitso')}"
    if mode == "testnet":
        return "testnet · binance"
    return "paper"


def get_execution_adapter() -> ExecutionAdapter:
    mode = exchange_mode()
    exchange_id = os.environ.get("EXCHANGE_ID", "bitso")
    if mode == "live":
        if exchange_id == "bitso":
            from src.execution.bitso import BitsoAdapter

            return BitsoAdapter()
        from src.execution.binance import BinanceAdapter

        return BinanceAdapter(mode="live")
    if mode == "testnet":
        from src.execution.binance import BinanceAdapter

        return BinanceAdapter(mode="testnet")
    from src.execution.adapter import PaperAdapter

    # Paper sandbox: el balance se siembra con el budget de trading (§8.8 — $1 local).
    budget = float(os.environ.get("HERMES_CAPITAL_USD", "1"))
    return PaperAdapter(initial_balance=budget)
