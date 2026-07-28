"""Tests de market_corpus (H14 F1) — parseo, filtros de universo y detección de huecos.

Todo offline: los zips se fabrican en memoria; no hay red ni GCS.
"""

import io
import zipfile

import pandas as pd
import pytest

from src.lab.market_corpus import (
    CUTOFF_MONTH,
    keep_symbol,
    month_gaps,
    month_of,
    parse_funding_zip,
    parse_kline_zip,
)


def _zip_bytes(csv: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.csv", csv)
    return buf.getvalue()


# ---------- universo ----------

@pytest.mark.parametrize(
    ("sym", "expected"),
    [
        ("BTCUSDT", True),
        ("LUNAUSDT", True),  # deslistado: SÍ entra (anti-supervivencia)
        ("BTCBUSD", False),  # quote BUSD duplica
        ("ETHUSDC", False),
        ("BTCUSDT_210625", False),  # quarterly con fecha
        ("BTCUSDT_SETTLED", False),
        ("AAPLUSDT", False),  # TRADIFI (acción tokenizada)
        ("XAUUSDT", False),  # TRADIFI (commodity)
        ("ETCUSDT", True),
    ],
)
def test_keep_symbol(sym: str, expected: bool) -> None:
    assert keep_symbol(sym) is expected


def test_month_of_klines_and_funding() -> None:
    klines_key = "data/futures/um/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-2021-03.zip"
    funding_key = "data/futures/um/monthly/fundingRate/LUNAUSDT/LUNAUSDT-fundingRate-2022-05.zip"
    assert month_of(klines_key) == "2021-03"
    assert month_of(funding_key) == "2022-05"


def test_cutoff_is_frozen() -> None:
    # DESIGN_H14 §2: el corte no se mueve con la fecha de corrida
    assert CUTOFF_MONTH == "2026-06"
    assert month_of("x/BTCUSDT-1d-2026-07.zip") > CUTOFF_MONTH


# ---------- parseo klines ----------

_KLINE_ROW_MS = (
    "1609459200000,29000,29500,28800,29400,1000,1609545599999,29200000,5000,600,17520000,0"
)
_KLINE_ROW_US = (
    "1609459200000000,29000,29500,28800,29400,1000,"
    "1609545599999999,29200000,5000,600,17520000,0"
)


def test_parse_kline_zip_sin_header_ms() -> None:
    df = parse_kline_zip(_zip_bytes(_KLINE_ROW_MS))
    assert len(df) == 1
    assert df["ts"].iloc[0] == pd.Timestamp("2021-01-01")
    assert df["close"].iloc[0] == 29400.0
    assert df["quote_volume"].iloc[0] == 29200000.0
    assert df["n_trades"].iloc[0] == 5000


def test_parse_kline_zip_con_header_y_microsegundos() -> None:
    csv = (
        "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
        "taker_buy_volume,taker_buy_quote_volume,ignore\n" + _KLINE_ROW_US
    )
    df = parse_kline_zip(_zip_bytes(csv))
    # µs 2025+: mismo instante que la fila en ms
    assert df["ts"].iloc[0] == pd.Timestamp("2021-01-01")
    assert df["open"].iloc[0] == 29000.0


# ---------- parseo funding ----------

def test_parse_funding_zip_con_header() -> None:
    csv = (
        "calc_time,funding_interval_hours,last_funding_rate\n"
        "1609459200000,8,0.0001\n1609488000000,8,-0.0002\n"
    )
    df = parse_funding_zip(_zip_bytes(csv))
    assert len(df) == 2
    assert df["funding_rate"].iloc[1] == -0.0002
    assert df["funding_interval_hours"].iloc[0] == 8
    assert df["ts"].iloc[0] == pd.Timestamp("2021-01-01")


def test_parse_funding_zip_sin_header_e_intervalo_4h() -> None:
    df = parse_funding_zip(_zip_bytes("1609459200000,4,0.0003\n"))
    assert df["funding_interval_hours"].iloc[0] == 4


# ---------- huecos ----------

def test_month_gaps() -> None:
    assert month_gaps(["2021-01", "2021-02", "2021-03"]) == 0
    assert month_gaps(["2021-01", "2021-04"]) == 2  # feb y mar faltan
    assert month_gaps(["2022-11", "2023-02"]) == 2  # cruza el año
    assert month_gaps(["2021-01"]) == 0
    assert month_gaps([]) == 0
