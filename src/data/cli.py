"""CLI entry point for data pipeline skills.

Usage:
  python -m src.data.cli ingest-bronze BTC/USDT 1h --from 2024-01-01 --to 2026-06-27
  python -m src.data.cli validate-bronze BTC/USDT 1h
  python -m src.data.cli transform-silver BTC/USDT 1h
  python -m src.data.cli validate-silver BTC/USDT 1h
  python -m src.data.cli backfill BTC/USDT,ETH/USDT 1h --from 2024-01-01 --to 2026-06-27
"""

import argparse
import sys
import time
from datetime import UTC, datetime


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def cmd_ingest_bronze(args: argparse.Namespace) -> None:
    from src.data.bronze.ingest import ingest

    since = _parse_date(args.since)
    until = _parse_date(args.until)
    print(f"[bronze] ingesting {args.symbol} {args.timeframe} {args.since}→{args.until}")
    count = ingest(args.symbol, args.timeframe, since, until)
    print(f"[bronze] ✅ {count} rows stored")


def cmd_validate_bronze(args: argparse.Namespace) -> None:
    from src.data.bronze.validate import validate

    result = validate(args.symbol, args.timeframe)
    print(f"[bronze:validate] {args.symbol} {args.timeframe}")
    print(f"  rows   : {result.rows}")
    print(f"  range  : {result.since} → {result.until}")
    print(f"  gaps   : {result.gaps}")
    print(f"  nulls  : {result.nulls}")
    if result.errors:
        for e in result.errors:
            print(f"  ❌ {e}")
        sys.exit(1)
    print("  ✅ OK")


def cmd_transform_silver(args: argparse.Namespace) -> None:
    from src.data.silver.transform import transform

    print(f"[silver] transforming {args.symbol} {args.timeframe} (may take a few minutes)")
    t0 = time.time()
    count = transform(args.symbol, args.timeframe)
    elapsed = time.time() - t0
    print(f"[silver] ✅ {count} rows written in {elapsed:.1f}s")


def cmd_validate_silver(args: argparse.Namespace) -> None:
    from src.data.silver.validate import validate

    result = validate(args.symbol, args.timeframe)
    print(f"[silver:validate] {args.symbol} {args.timeframe}")
    print(f"  rows         : {result.rows}")
    print(f"  with hurst   : {result.rows_with_hurst}")
    print(f"  with garch   : {result.rows_with_garch}")
    print(f"  regime dist  : {result.regime_dist}")
    if result.errors:
        for e in result.errors:
            print(f"  ❌ {e}")
        sys.exit(1)
    print("  ✅ OK")


def cmd_ingest_news(args: argparse.Namespace) -> None:
    from src.data.bronze.news import ingest_news

    symbols = [s.strip() for s in args.symbols.split(",")]
    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None
    print(f"[news] fetching {symbols} from {sources or 'all configured sources'}")
    summary = ingest_news(symbols, sources, limit=args.limit, scan_injection=not args.no_scan)
    print(
        f"[news] fetched={summary['fetched']} stored={summary['stored']} "
        f"injection_flagged={summary['flagged']}"
    )
    print(f"[news] by source: {summary['by_source']}")


def cmd_backfill(args: argparse.Namespace) -> None:
    from src.data.bronze.ingest import ingest
    from src.data.bronze.validate import validate as bvalidate
    from src.data.silver.transform import transform
    from src.data.silver.validate import validate as svalidate

    symbols = [s.strip() for s in args.symbols.split(",")]
    since = _parse_date(args.since)
    until = _parse_date(args.until)
    days = (until - since).days

    print(f"[backfill] {len(symbols)} symbols · {args.timeframe} · {days} days")
    if days > 365:
        print(f"[backfill] ⚠️  largo rango ({days}d) — puede tardar varios minutos")

    failed = []
    for symbol in symbols:
        print(f"\n── {symbol} ──")
        try:
            count = ingest(symbol, args.timeframe, since, until)
            print(f"  bronze ingest  ✅ {count} rows")

            b = bvalidate(symbol, args.timeframe)
            if not b.ok:
                raise RuntimeError(f"bronze validate failed: {b.errors}")
            print(f"  bronze valid   ✅ {b.rows} rows, {b.gaps} gaps")

            written = transform(symbol, args.timeframe)
            print(f"  silver transform ✅ {written} rows")

            s = svalidate(symbol, args.timeframe)
            if not s.ok:
                raise RuntimeError(f"silver validate failed: {s.errors}")
            print(f"  silver valid   ✅ hurst={s.rows_with_hurst} garch={s.rows_with_garch}")
            print(f"  regime dist    {s.regime_dist}")
        except Exception as exc:
            print(f"  ❌ {exc}")
            failed.append(symbol)

    print(f"\n[backfill] done — {len(symbols) - len(failed)}/{len(symbols)} OK")
    if failed:
        print(f"  failed: {failed}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="hermes-data")
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest-bronze
    p = sub.add_parser("ingest-bronze")
    p.add_argument("symbol")
    p.add_argument("timeframe")
    p.add_argument("--from", dest="since", required=True)
    p.add_argument("--to", dest="until", required=True)

    # validate-bronze
    p = sub.add_parser("validate-bronze")
    p.add_argument("symbol")
    p.add_argument("timeframe")

    # transform-silver
    p = sub.add_parser("transform-silver")
    p.add_argument("symbol")
    p.add_argument("timeframe")

    # validate-silver
    p = sub.add_parser("validate-silver")
    p.add_argument("symbol")
    p.add_argument("timeframe")

    # backfill
    p = sub.add_parser("backfill")
    p.add_argument("symbols")
    p.add_argument("timeframe")
    p.add_argument("--from", dest="since", required=True)
    p.add_argument("--to", dest="until", required=True)

    # ingest-news
    p = sub.add_parser("ingest-news")
    p.add_argument("symbols")
    p.add_argument("--sources", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--no-scan", action="store_true", help="skip prompt-injection scan")

    args = parser.parse_args()

    dispatch = {
        "ingest-bronze": cmd_ingest_bronze,
        "validate-bronze": cmd_validate_bronze,
        "transform-silver": cmd_transform_silver,
        "validate-silver": cmd_validate_silver,
        "backfill": cmd_backfill,
        "ingest-news": cmd_ingest_news,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
