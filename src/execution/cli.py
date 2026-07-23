"""CLI entry point for sending one execution order.

Lives in its own module (not imported by src/execution/__init__.py) so that
`python -m src.execution.cli` does not trigger the "found in sys.modules" double
-import RuntimeWarning that `python -m src.execution.adapter` did.

Used by the execution:paper / execution:live skills.
"""

from __future__ import annotations

from src.execution.adapter import ExecutionAdapter, PaperAdapter


def _build_adapter(mode: str) -> ExecutionAdapter:
    """Pick an adapter from an EXCHANGE_MODE-style string."""
    import os

    if mode == "live" and os.environ.get("EXCHANGE_ID", "bitso") == "bitso":
        from src.execution.bitso import BitsoAdapter

        return BitsoAdapter()
    if mode in ("testnet", "live"):
        from src.execution.binance import BinanceAdapter

        return BinanceAdapter(mode=mode)
    return PaperAdapter()


def main() -> int:
    import argparse
    import dataclasses
    import json

    parser = argparse.ArgumentParser(description="Send one execution order.")
    parser.add_argument("--mode", default="paper", choices=["paper", "testnet", "live"])
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--size-usd", type=float, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    decision = {
        "symbol": args.symbol,
        "action": args.side.upper(),
        "size_usd": args.size_usd,
    }

    adapter = _build_adapter(args.mode)
    result = adapter.execute(decision, args.run_id)
    print(json.dumps(dataclasses.asdict(result), default=str, indent=2))
    return 0 if result.status in ("FILLED", "CANCELLED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
