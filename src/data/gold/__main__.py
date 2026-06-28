"""python -m src.data.gold.aggregate --symbol BTC/USDT,ETH/USDT"""
import argparse
import json
import os

from src.data.gold.aggregate import aggregate


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--timeframe", default="1h")
    args = parser.parse_args()

    if args.symbol:
        symbols = [s.strip() for s in args.symbol.split(",")]
    else:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    signals = aggregate(symbols, args.timeframe)

    print(f"\n── Gold signals ({len(signals)} símbolos) ──")
    for s in signals:
        print(f"  {s['symbol']:12s}  regime={s['regime']:14s}  conf={s['regime_conf']:.2f}"
              f"  hurst={s['features']['hurst']}  garch_vol={s['features']['garch_vol']}")

    print(f"\n{json.dumps(signals, indent=2)}")


if __name__ == "__main__":
    main()
