"""market_corpus — corpus H14 anti-supervivencia desde data.binance.vision (F1).

Enumera TODOS los perpetuos USDT-M históricos del archivo público de Binance
(listing S3 — los deslistados conservan sus carpetas), baja klines 1d + funding
mensuales hasta el corte fijo del pre-registro, y construye:

  bronze/vision_um_daily/<SYM>.parquet    klines diarios por símbolo
  bronze/vision_funding/<SYM>.parquet     funding por símbolo (con interval_hours)
  datasets/market_daily_v1.parquet        panel consolidado
  datasets/market_funding_v1.parquet      funding consolidado
  reports/h14_corpus_quality.{json,md}    calidad + cruce vs daily_v1 (trampa tz H8)

Pre-registro: DESIGN_H14 §6. Ingesta/descriptivo — NO cuenta al DSR.
El corte temporal (CUTOFF_MONTH) es fijo por §2 — no se mueve con la fecha de corrida.
La lista TRADIFI se congeló de fapi exchangeInfo el 2026-07-26 (el endpoint fapi da 451
desde regiones US de GCP; el archivo Vision abre desde todas — DESIGN_H13 §11).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.market_corpus"
"""

import io
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

import httpx
import numpy as np
import pandas as pd

from src.lab import gcs

S3_ENDPOINT = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
CDN = "https://data.binance.vision"
KLINES_PREFIX = "data/futures/um/monthly/klines/"
FUNDING_PREFIX = "data/futures/um/monthly/fundingRate/"
CUTOFF_MONTH = "2026-06"  # DESIGN_H14 §2 — fijo, pase lo que pase con la descarga
MAX_WORKERS = 24
RETRIES = 3
MAX_FAILED_FRACTION = 0.01  # >1% de archivos caídos = corpus inválido (sin caps silenciosos)

KLINE_COLS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "n_trades", "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]

# Acciones/ETFs/commodities tokenizados (contractType TRADIFI_PERPETUAL) — no son cripto.
# Snapshot fapi exchangeInfo 2026-07-26; los TRADIFI existen desde 2025, así que el
# snapshot cubre todo el rango del corpus (corte 2026-06). Si un excluido tuviera datos
# pre-2025 sería reuso de ticker de un perp cripto viejo → el reporte de calidad lo marca.
TRADIFI = {
    "AAOIUSDT", "AAPLUSDT", "ADBEUSDT", "ALABUSDT", "AMATUSDT", "AMDUSDT", "AMZNUSDT",
    "ANTHROPICUSDT", "APPUSDT", "ARMUSDT", "ASMLUSDT", "ASTSUSDT", "AVGOUSDT", "AXTIUSDT",
    "BABAUSDT", "BBXUSDT", "BEUSDT", "BMNRUSDT", "BNCUSDT", "BOTUSDT", "BRKBUSDT",
    "BSPUSDT", "BXUSDT", "BZUSDT", "CATUSDT", "CBRSUSDT", "CIENUSDT", "CLUSDT",
    "COHRUSDT", "COINUSDT", "COPPERUSDT", "COSTUSDT", "CRCLUSDT", "CRDOUSDT", "CRMUSDT",
    "CRWDUSDT", "CRWVUSDT", "CSCOUSDT", "DELLUSDT", "DISUSDT", "DKNGUSDT", "DRAMUSDT",
    "EBAYUSDT", "EWJUSDT", "EWTUSDT", "EWYUSDT", "EWZUSDT", "FLEXUSDT", "FLNCUSDT",
    "FWDIUSDT", "GEVUSDT", "GLWUSDT", "GMEUSDT", "GOOGLUSDT", "HDUSDT", "HIMSUSDT",
    "HK0700USDT", "HK1810USDT", "HOODUSDT", "HPEUSDT", "HYUNDAIUSDT", "IBMUSDT",
    "INTCUSDT", "INTWUSDT", "IRENUSDT", "IWMUSDT", "JPMUSDT", "KLACUSDT", "KORUUSDT",
    "KSTRUSDT", "LITEUSDT", "LLYUSDT", "LRCXUSDT", "METAUSDT", "MINIMAXUSDT", "MRVLUSDT",
    "MSFTUSDT", "MSTRUSDT", "MUUSDT", "MUUUSDT", "MVLLUSDT", "NATGASUSDT", "NBISUSDT",
    "NFLXUSDT", "NOKUSDT", "NOWUSDT", "NVDAUSDT", "NVOUSDT", "ONDSUSDT", "OPENAIUSDT",
    "ORCLUSDT", "PANWUSDT", "PAYPUSDT", "PENGUSDT", "PLTRUSDT", "POPMARTUSDT", "QCOMUSDT",
    "QNTXUSDT", "QQQUSDT", "RIVNUSDT", "RKLBUSDT", "SAMSUNGUSDT", "SHAZUSDT",
    "SKHYNIXUSDT", "SKHYUSDT", "SMCIUSDT", "SNDKUSDT", "SNOWUSDT", "SNXXUSDT", "SOFIUSDT",
    "SONYUSDT", "SOXLUSDT", "SOXSUSDT", "SPCXUSDT", "SPYUSDT", "SQQQUSDT", "STRCUSDT",
    "STXXUSDT", "TENCENTUSDT", "TERUSDT", "TQQQUSDT", "TSLAUSDT", "TSMUSDT", "TTWOUSDT",
    "TXNUSDT", "TZAUSDT", "UBERUSDT", "URNMUSDT", "USARUSDT", "UVXYUSDT", "VRTUSDT",
    "VUSDT", "WDCUSDT", "WENUSDT", "WMTUSDT", "XAGUSDT", "XAUUSDT", "XBIUSDT", "XLEUSDT",
    "XPDUSDT", "XPTUSDT", "ZHIPUUSDT", "ZMUSDT",
}


def keep_symbol(sym: str) -> bool:
    """Universo H14: perps USDT-M cripto. Fuera: TRADIFI, variantes `_` (quarterlies
    con fecha, `_SETTLED`) y todo lo que no liquide en USDT (BUSD/USDC duplican)."""
    return sym.endswith("USDT") and "_" not in sym and sym not in TRADIFI


def month_of(key: str) -> str:
    """.../BTCUSDT-1d-2021-03.zip → '2021-03' (funding: ...-fundingRate-2021-03.zip)."""
    stem = key.rsplit("/", 1)[-1].removesuffix(".zip")
    parts = stem.rsplit("-", 2)
    return f"{parts[-2]}-{parts[-1]}"


def _s3_xml(client: httpx.Client, params: dict[str, str]) -> ElementTree.Element:
    for attempt in range(RETRIES):
        try:
            r = client.get(S3_ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            # S314: la fuente es el archivo oficial de Binance sobre TLS (listing
            # XML plano, sin DTD/entidades); ElementTree moderno no expande entidades
            return ElementTree.fromstring(r.content)  # noqa: S314
        except (httpx.HTTPError, ElementTree.ParseError):
            if attempt == RETRIES - 1:
                raise
    raise RuntimeError("unreachable")


def _strip(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def list_symbol_dirs(client: httpx.Client, prefix: str) -> list[str]:
    """CommonPrefixes bajo `prefix` (una carpeta por símbolo), con paginación."""
    out: list[str] = []
    marker = ""
    while True:
        params = {"delimiter": "/", "prefix": prefix}
        if marker:
            params["marker"] = marker
        root = _s3_xml(client, params)
        truncated = False
        for el in root:
            tag = _strip(el.tag)
            if tag == "CommonPrefixes":
                for sub in el:
                    if _strip(sub.tag) == "Prefix" and sub.text:
                        out.append(sub.text.removeprefix(prefix).rstrip("/"))
            elif tag == "IsTruncated":
                truncated = (el.text or "").lower() == "true"
            elif tag == "NextMarker":
                marker = el.text or ""
        if not truncated:
            return out
        if not marker:  # sin NextMarker: continuar desde la última key/prefix vista
            marker = prefix + out[-1] + "/"


def list_zip_keys(client: httpx.Client, prefix: str) -> list[str]:
    """Keys .zip bajo `prefix` (sin delimiter — lista objetos), con paginación."""
    out: list[str] = []
    marker = ""
    while True:
        params = {"prefix": prefix}
        if marker:
            params["marker"] = marker
        root = _s3_xml(client, params)
        truncated, last_key = False, ""
        for el in root:
            tag = _strip(el.tag)
            if tag == "Contents":
                for sub in el:
                    if _strip(sub.tag) == "Key" and sub.text:
                        last_key = sub.text
                        if sub.text.endswith(".zip"):
                            out.append(sub.text)
            elif tag == "IsTruncated":
                truncated = (el.text or "").lower() == "true"
            elif tag == "NextMarker":
                marker = el.text or ""
        if not truncated:
            return out
        if not marker:
            marker = last_key


def _normalize_epoch(ts: pd.Series) -> pd.Series:
    """Epoch ms — el archivo cambió a µs en algunos datasets 2025+: >1e14 → ÷1000."""
    t = pd.to_numeric(ts, errors="coerce").astype("float64")
    return (t.where(t < 1e14, t / 1000)).round().astype("int64")


def parse_kline_zip(raw: bytes) -> pd.DataFrame:
    """CSV de klines dentro del zip mensual. Los archivos viejos no traen header,
    los nuevos sí ('open_time,...') — se detecta por la primera línea."""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        data = zf.read(zf.namelist()[0])
    skip = 1 if data[:9] == b"open_time" else 0
    df = pd.read_csv(io.BytesIO(data), header=None, skiprows=skip, names=KLINE_COLS)
    ts = pd.to_datetime(_normalize_epoch(df["open_time"]), unit="ms", utc=True)
    out = pd.DataFrame(
        {
            "ts": ts.dt.tz_localize(None),
            "open": df["open"].astype(float),
            "high": df["high"].astype(float),
            "low": df["low"].astype(float),
            "close": df["close"].astype(float),
            "volume": df["volume"].astype(float),
            "quote_volume": df["quote_volume"].astype(float),
            "n_trades": df["n_trades"].astype("int64"),
        }
    )
    return out


def parse_funding_zip(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        data = zf.read(zf.namelist()[0])
    skip = 1 if data[:9] == b"calc_time" else 0
    df = pd.read_csv(
        io.BytesIO(data), header=None, skiprows=skip,
        names=["calc_time", "funding_interval_hours", "last_funding_rate"],
    )
    ts = pd.to_datetime(_normalize_epoch(df["calc_time"]), unit="ms", utc=True)
    return pd.DataFrame(
        {
            "ts": ts.dt.tz_localize(None),
            "funding_interval_hours": pd.to_numeric(
                df["funding_interval_hours"], errors="coerce"
            ),
            "funding_rate": pd.to_numeric(df["last_funding_rate"], errors="coerce"),
        }
    )


def _fetch_zip(client: httpx.Client, key: str) -> bytes | None:
    for attempt in range(RETRIES):
        try:
            r = client.get(f"{CDN}/{key}", timeout=60)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError:
            if attempt == RETRIES - 1:
                return None
    return None


def month_gaps(months: list[str]) -> int:
    """Meses faltantes entre el primero y el último listado (huecos del archivo)."""
    if len(months) < 2:
        return 0
    idx = pd.PeriodIndex(sorted(months), freq="M")
    return int((idx[-1] - idx[0]).n + 1 - len(idx))


def _pull_symbol(
    client: httpx.Client, sym: str, subprefix: str, parser: Any, bronze_dir: str
) -> dict[str, Any]:
    keys = [k for k in list_zip_keys(client, subprefix) if month_of(k) <= CUTOFF_MONTH]
    frames, failed = [], 0
    for key in keys:
        raw = _fetch_zip(client, key)
        if raw is None:
            failed += 1
            continue
        frames.append(parser(raw))
    if not frames:
        return {"symbol": sym, "files": len(keys), "failed": failed, "rows": 0}
    df = pd.concat(frames, ignore_index=True).sort_values("ts")
    df = df.drop_duplicates(subset="ts", keep="last")
    df.insert(0, "symbol", sym)
    gcs.upload_parquet(df, f"{bronze_dir}/{sym}.parquet")
    return {
        "symbol": sym, "files": len(keys), "failed": failed, "rows": len(df),
        "first": str(df["ts"].iloc[0].date()), "last": str(df["ts"].iloc[-1].date()),
        "gaps": month_gaps([month_of(k) for k in keys]), "frame": df,
    }


def cross_check_h13(daily: pd.DataFrame) -> list[dict[str, Any]]:
    """σ y ρ₁ de los 29 símbolos del corpus H13 (spot, daily_v1) vs Vision (perp).
    Caza la trampa tz de H8: un desfase de barra dispara diferencias grandes."""
    try:
        ref = gcs.read_parquet("datasets/daily_v1.parquet")
    except Exception as exc:  # daily_v1 ausente no invalida el corpus nuevo
        print(f"[market_corpus] WARN cruce daily_v1 no disponible: {exc}")
        return []
    ref = ref[ref["source"] == "binance"]
    out: list[dict[str, Any]] = []
    for base, g in ref.groupby("symbol"):
        sym = f"{base}USDT"
        mine = daily[daily["symbol"] == sym]
        if mine.empty:
            continue
        a = g.set_index(pd.to_datetime(g["ts"]))["close"].sort_index()
        b = mine.set_index(pd.to_datetime(mine["ts"]))["close"].sort_index()
        common = a.index.intersection(b.index)
        if len(common) < 200:
            continue
        ra = np.log(a.loc[common]).diff().dropna()
        rb = np.log(b.loc[common]).diff().dropna()
        sd_a, sd_b = float(ra.std()), float(rb.std())
        rho_a = float(ra.autocorr(1))
        rho_b = float(rb.autocorr(1))
        out.append(
            {
                "symbol": sym, "n": int(len(common)),
                "sigma_ref": round(sd_a, 5), "sigma_vision": round(sd_b, 5),
                "rho1_ref": round(rho_a, 4), "rho1_vision": round(rho_b, 4),
                "sigma_ok": bool(abs(sd_a - sd_b) <= 1e-2),
                "rho1_ok": bool(abs(rho_a - rho_b) <= 1e-2),
            }
        )
    return out


def main() -> int:
    t0 = datetime.now(UTC)
    with httpx.Client() as client:
        dirs = list_symbol_dirs(client, KLINES_PREFIX)
        universe = sorted(s for s in dirs if keep_symbol(s))
        excluded = sorted(set(dirs) - set(universe))
        print(f"[market_corpus] listado: {len(dirs)} carpetas → {len(universe)} en universo")

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            kline_stats = list(
                pool.map(
                    lambda s: _pull_symbol(
                        client, s, f"{KLINES_PREFIX}{s}/1d/", parse_kline_zip,
                        "bronze/vision_um_daily",
                    ),
                    universe,
                )
            )
            funding_stats = list(
                pool.map(
                    lambda s: _pull_symbol(
                        client, s, f"{FUNDING_PREFIX}{s}/", parse_funding_zip,
                        "bronze/vision_funding",
                    ),
                    universe,
                )
            )
            # reuso de ticker: un "TRADIFI" con klines pre-2025 sería un perp cripto
            # viejo cuyo nombre reutilizó una acción tokenizada → se marca, no se baja
            tradifi_present = sorted(TRADIFI & set(dirs))
            first_months = list(
                pool.map(
                    lambda s: (
                        s,
                        min(
                            (month_of(k) for k in list_zip_keys(client, f"{KLINES_PREFIX}{s}/1d/")),
                            default="9999-99",
                        ),
                    ),
                    tradifi_present,
                )
            )

    daily = pd.concat(
        [s.pop("frame") for s in kline_stats if "frame" in s], ignore_index=True
    )
    funding = pd.concat(
        [s.pop("frame") for s in funding_stats if "frame" in s], ignore_index=True
    )

    total_files = sum(s["files"] for s in kline_stats + funding_stats)
    total_failed = sum(s["failed"] for s in kline_stats + funding_stats)
    if total_files and total_failed / total_files > MAX_FAILED_FRACTION:
        print(
            f"[market_corpus] ERROR: {total_failed}/{total_files} archivos caídos "
            f"(> {MAX_FAILED_FRACTION:.0%})"
        )
        return 1

    gcs.upload_parquet(daily, "datasets/market_daily_v1.parquet")
    gcs.upload_parquet(funding, "datasets/market_funding_v1.parquet")

    dead = [s["symbol"] for s in kline_stats if s.get("last", "9999") < "2026-06-01"]
    tradifi_suspect = [s for s, first in first_months if first < "2025-01"]
    checks = cross_check_h13(daily)
    bad_checks = [c for c in checks if not (c["sigma_ok"] and c["rho1_ok"])]

    quality: dict[str, Any] = {
        "generated": t0.isoformat(),
        "cutoff_month": CUTOFF_MONTH,
        "dirs_listed": len(dirs),
        "universe": len(universe),
        "excluded": {"count": len(excluded), "symbols": excluded},
        "rows_daily": int(len(daily)),
        "rows_funding": int(len(funding)),
        "files": {"total": total_files, "failed": total_failed},
        "dead_symbols": {"count": len(dead), "symbols": dead},
        "gaps_total": int(sum(s.get("gaps", 0) for s in kline_stats)),
        "per_symbol": [{k: v for k, v in s.items() if k != "frame"} for s in kline_stats],
        "cross_check_daily_v1": checks,
        "cross_check_failures": bad_checks,
        "tradifi_excluded": tradifi_present,
        "tradifi_suspect_pre2025": tradifi_suspect,
    }
    gcs.upload_json(quality, "reports/h14_corpus_quality.json")

    lines = [
        "# Calidad del corpus H14 (Vision UM, anti-supervivencia)",
        f"\nGenerado {t0.isoformat()} · corte {CUTOFF_MONTH} (fijo §2)\n",
        f"- Carpetas listadas: {len(dirs)} · universo: {len(universe)} · "
        f"excluidas: {len(excluded)}",
        f"- Filas daily: {len(daily):,} · funding: {len(funding):,}",
        f"- Archivos: {total_files:,} · caídos: {total_failed}",
        f"- Símbolos muertos (última barra < 2026-06): {len(dead)}",
        f"- Huecos de meses en el archivo: {sum(s.get('gaps', 0) for s in kline_stats)}",
        f"- Cruce vs daily_v1 (29 H13): {len(checks)} comparados, "
        f"{len(bad_checks)} fuera de tolerancia",
    ]
    if bad_checks:
        lines.append("\n| símbolo | σ ref | σ vision | ρ₁ ref | ρ₁ vision |")
        lines.append("|---|---|---|---|---|")
        for c in bad_checks:
            lines.append(
                f"| {c['symbol']} | {c['sigma_ref']} | {c['sigma_vision']} "
                f"| {c['rho1_ref']} | {c['rho1_vision']} |"
            )
    gcs.upload_text("\n".join(lines), "reports/h14_corpus_quality.md")

    dt = (datetime.now(UTC) - t0).total_seconds()
    print(
        f"[market_corpus] {len(universe)} símbolos · {len(daily):,} filas daily · "
        f"{len(funding):,} funding · {len(dead)} muertos · {dt:.0f}s"
    )
    print(f"[market_corpus] cruce daily_v1: {len(bad_checks)} fuera de tolerancia de {len(checks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
