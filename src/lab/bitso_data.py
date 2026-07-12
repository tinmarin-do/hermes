"""Probe + backfill de libros MXN de Bitso (corre EN la nube — Bitso no bloquea GCP).

Modos:
  python -m src.lab.bitso_data --probe      → reports/bitso_universe_audit.md
  python -m src.lab.bitso_data --backfill   → bronze/bitso_ohlcv_1h/<BOOK>.parquet
  python -m src.lab.bitso_data --delta      → append de velas nuevas a los parquet

El probe mide profundidad/completitud/volumen por libro; el backfill baja TODO el
histórico 1h que el venue entregue (incluye usdt_mxn — la serie FX del venue).
El delta trae solo lo posterior a la última vela de cada parquet (lo usa el
shadow producer H12 antes de cada emisión — Bitso no bloquea GCP).
"""

import argparse
import sys
import time
from datetime import UTC, datetime

import ccxt
import pandas as pd

from src.lab import gcs

BATCH = 1000
SLEEP = 0.35
EARLIEST = datetime(2016, 1, 1, tzinfo=UTC)  # Bitso existe desde 2014; margen amplio


def _mxn_books(ex: ccxt.bitso) -> list[str]:
    # Bitso reporta active=None en TODOS los libros (verificado 2026-07-11):
    # solo excluir los explícitamente inactivos (active is False).
    markets = ex.load_markets()
    return sorted(
        s for s, m in markets.items() if m.get("quote") == "MXN" and m.get("active") is not False
    )


JUMP_MS = 180 * 24 * 3600 * 1000  # si el venue devuelve vacío pre-listado, saltar 180d


def _fetch_all(ex: ccxt.bitso, book: str, since: datetime) -> pd.DataFrame:
    cursor = int(since.timestamp() * 1000)
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    rows: list[list[float]] = []
    while cursor < now_ms:
        candles = ex.fetch_ohlcv(book, "1h", since=cursor, limit=BATCH)
        if not candles:
            if not rows:
                cursor += JUMP_MS  # aún no encontramos el inicio del listado
                continue
            break
        rows.extend(candles)
        last = candles[-1][0]
        if last <= cursor:
            break
        cursor = last + 1
        if len(candles) == BATCH:
            time.sleep(SLEEP)
    if not rows:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True).dt.tz_localize(None)
    return df.drop_duplicates(subset="ts").sort_values("ts")[
        ["ts", "open", "high", "low", "close", "volume"]
    ]


def probe() -> int:
    # Si el backfill ya corrió, la auditoría se deriva del parquet (sin re-pegar al API).
    existing = gcs.list_blobs("bronze/bitso_ohlcv_1h/")
    if existing:
        return _audit_from_parquet(existing)
    ex = ccxt.bitso({"enableRateLimit": True})
    books = _mxn_books(ex)
    print(f"[probe] {len(books)} libros MXN activos en Bitso")
    lines = [
        "# Auditoría de universo Bitso (libros MXN) — arco H11",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · Fuente: ccxt.bitso fetch_ohlcv 1h\n",
        "| libro | primera vela | última vela | velas | completitud | vol MXN medio/día |",
        "|---|---|---|---|---|---|",
    ]
    audit = {}
    for book in books:
        try:
            df = _fetch_all(ex, book, EARLIEST)
        except Exception as e:  # noqa: BLE001
            lines.append(f"| {book} | ERROR {e} | | | | |")
            continue
        if df.empty:
            lines.append(f"| {book} | sin data | | 0 | | |")
            continue
        hours = int((df.ts.max() - df.ts.min()).total_seconds() // 3600) + 1
        comp = len(df) / hours if hours else 0
        vol_mxn_day = float((df.volume * df.close).tail(24 * 30).sum() / 30)
        audit[book] = {
            "first": str(df.ts.min()),
            "last": str(df.ts.max()),
            "candles": len(df),
            "completeness": round(comp, 4),
            "vol_mxn_day_30d": round(vol_mxn_day, 0),
        }
        lines.append(
            f"| {book} | {df.ts.min():%Y-%m-%d} | {df.ts.max():%Y-%m-%d} | {len(df):,} "
            f"| {comp:.1%} | {vol_mxn_day:,.0f} |"
        )
        print(
            f"  {book:12s} {df.ts.min():%Y-%m-%d} → {df.ts.max():%Y-%m-%d}  "
            f"{len(df):>7,} velas  comp {comp:.1%}"
        )
    gcs.upload_text("\n".join(lines), "reports/bitso_universe_audit.md")
    gcs.upload_json(audit, "reports/bitso_universe_audit.json")
    print("[probe] → reports/bitso_universe_audit.md")
    return 0


def _audit_from_parquet(blob_names: list[str]) -> int:
    print(f"[probe] derivando auditoría de {len(blob_names)} parquet ya backfilleados")
    lines = [
        "# Auditoría de universo Bitso (libros MXN) — arco H11",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · Fuente: parquet del backfill\n",
        "| libro | primera vela | última vela | velas | completitud | vol MXN medio/día |",
        "|---|---|---|---|---|---|",
    ]
    audit = {}
    for name in sorted(blob_names):
        book = name.split("/")[-1].removesuffix(".parquet").replace("_", "/")
        df = gcs.read_parquet(name)
        if df.empty:
            continue
        hours = int((df.ts.max() - df.ts.min()).total_seconds() // 3600) + 1
        comp = len(df) / hours if hours else 0
        vol_mxn_day = float((df.volume * df.close).tail(24 * 30).sum() / 30)
        audit[book] = {
            "first": str(df.ts.min()),
            "last": str(df.ts.max()),
            "candles": len(df),
            "completeness": round(comp, 4),
            "vol_mxn_day_30d": round(vol_mxn_day, 0),
        }
        lines.append(
            f"| {book} | {df.ts.min():%Y-%m-%d} | {df.ts.max():%Y-%m-%d} | {len(df):,} "
            f"| {comp:.1%} | {vol_mxn_day:,.0f} |"
        )
    gcs.upload_text("\n".join(lines), "reports/bitso_universe_audit.md")
    gcs.upload_json(audit, "reports/bitso_universe_audit.json")
    print("[probe] → reports/bitso_universe_audit.md")
    return 0


def backfill() -> int:
    ex = ccxt.bitso({"enableRateLimit": True})
    books = _mxn_books(ex)
    quality = {}
    for book in books:
        try:
            df = _fetch_all(ex, book, EARLIEST)
        except Exception as e:  # noqa: BLE001
            print(f"  {book:12s} ERROR: {e}")
            continue
        if df.empty:
            continue
        gcs.upload_parquet(df, f"bronze/bitso_ohlcv_1h/{gcs.safe_name(book)}.parquet")
        hours = int((df.ts.max() - df.ts.min()).total_seconds() // 3600) + 1
        quality[book] = {
            "rows": len(df),
            "gaps": int(hours - df.ts.nunique()),
            "from": str(df.ts.min()),
            "to": str(df.ts.max()),
        }
        print(f"  {book:12s} {len(df):>7,} velas → parquet")
    gcs.upload_json(
        {"source": "bitso", "exported_at": datetime.now(UTC).isoformat(), "books": quality},
        "reports/data_quality_bitso.json",
    )
    print(f"[backfill] {len(quality)} libros → bronze/bitso_ohlcv_1h/")
    return 0


def delta() -> int:
    """Append incremental: por parquet existente, baja velas > última ts y sube."""
    ex = ccxt.bitso({"enableRateLimit": True})
    updated = 0
    for name in sorted(gcs.list_blobs("bronze/bitso_ohlcv_1h/")):
        book = name.split("/")[-1].removesuffix(".parquet").replace("_", "/")
        old = gcs.read_parquet(name)
        last = pd.Timestamp(old.ts.max())
        try:
            new = _fetch_all(ex, book, last.tz_localize(UTC) + pd.Timedelta(hours=1))
        except Exception as e:  # noqa: BLE001
            print(f"  {book:12s} ERROR delta: {e}")
            continue
        new = new[new.ts > last]
        if new.empty:
            continue
        merged = (
            pd.concat([old, new], ignore_index=True).drop_duplicates(subset="ts").sort_values("ts")
        )
        gcs.upload_parquet(merged, name)
        updated += 1
        print(f"  {book:12s} +{len(new):,} velas (→ {merged.ts.max()})")
    print(f"[delta] {updated} libros actualizados")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--probe", action="store_true")
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--delta", action="store_true")
    a = p.parse_args()
    if a.probe:
        return probe()
    if a.backfill:
        return backfill()
    if a.delta:
        return delta()
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
