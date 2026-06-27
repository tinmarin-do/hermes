"""CI cost check — fails if LLM budget exceeds threshold percentage."""
import argparse
import re
import sys


def parse_ledger(path: str) -> tuple[float, float]:
    """Return (accumulated, cap) from ledger markdown."""
    cap = 150.0
    accumulated = 0.0
    with open(path) as f:
        for line in f:
            if "| APERTURA-MES" in line or line.startswith("| fecha"):
                continue
            # Extract last numeric column as accumulated
            cols = [c.strip() for c in line.split("|") if c.strip()]
            if len(cols) >= 5 and cols[0] not in ("fecha", "—", "CIERRE-MES"):
                try:
                    accumulated = float(cols[-2].replace("$", ""))
                except (ValueError, IndexError):
                    pass
    return accumulated, cap


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--cap", type=float, default=150.0)
    parser.add_argument("--fail-at-pct", type=float, default=95.0)
    args = parser.parse_args()

    accumulated, _ = parse_ledger(args.ledger)
    pct = (accumulated / args.cap) * 100 if args.cap > 0 else 0

    print(f"LLM spend: ${accumulated:.2f} / ${args.cap:.2f} ({pct:.1f}%)")

    if pct >= args.fail_at_pct:
        print(f"❌ Budget at {pct:.1f}% — exceeds {args.fail_at_pct}% threshold")
        sys.exit(1)

    print(f"✅ Budget OK ({pct:.1f}% used)")


if __name__ == "__main__":
    main()
