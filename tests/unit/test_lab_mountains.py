"""Tests del catálogo de montañas H13 §5a — canary anti-hindsight incluido."""

import numpy as np
import pandas as pd
import pytest

from src.lab.mountains import (
    catalog_series,
    mountains_from_pivots,
    shape_vector,
    synthetic_twin,
    zigzag_pivots,
)

pytestmark = pytest.mark.unit


def _series(vals: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(vals), freq="D")
    return pd.Series(vals, index=idx, dtype=float)


def test_zigzag_detecta_montana_simple() -> None:
    # valle 100 → pico 150 → valle 105 con retrocesos > 20%
    closes = np.array([100, 110, 125, 140, 150, 138, 120, 105, 130, 140], dtype=float)
    pivots = zigzag_pivots(closes, tol=0.10)
    kinds = [p.kind for p in pivots]
    assert -1 in kinds and 1 in kinds
    peak = next(p for p in pivots if p.kind == 1)
    assert closes[peak.idx] == 150.0
    assert peak.confirm_idx > peak.idx  # confirmación siempre POSTERIOR al extremo


def test_zigzag_serie_monotona_no_inventa_montanas() -> None:
    closes = np.linspace(100, 200, 50)
    ts = pd.date_range("2024-01-01", periods=50, freq="D")
    pivots = zigzag_pivots(closes, tol=0.05)
    assert mountains_from_pivots(closes, pd.DatetimeIndex(ts), pivots, 0.05, "X") == []


def test_canary_anti_hindsight() -> None:
    """Montañas CONFIRMADAS hasta t deben ser idénticas con o sin el futuro."""
    rng = np.random.default_rng(7)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, 600)))
    ts = pd.DatetimeIndex(pd.date_range("2023-01-01", periods=600, freq="D"))
    t = 400
    full = mountains_from_pivots(closes, ts, zigzag_pivots(closes, 0.10), 0.10, "X")
    trunc = mountains_from_pivots(closes[:t], ts[:t], zigzag_pivots(closes[:t], 0.10), 0.10, "X")
    full_confirmed = [m for m in full if m["confirm_idx_v2"] < t]
    assert trunc[: len(full_confirmed)] == full_confirmed


def test_shape_sin_escala() -> None:
    """Misma silueta a distinta duración y altura → mismo vector de forma."""
    small = np.array([100, 105, 110, 105, 100], dtype=float)
    big_t = np.interp(np.linspace(0, 4, 17), np.arange(5), small)  # 4 días → 16 días
    big = big_t * 50  # ×50 en precio
    assert np.allclose(shape_vector(small), shape_vector(big), atol=1e-9)
    sv = shape_vector(small)
    assert sv.min() == 0.0 and sv.max() == 1.0


def test_catalog_archiva_escala() -> None:
    rng = np.random.default_rng(3)
    closes = _series((100 * np.exp(np.cumsum(rng.normal(0, 0.04, 400)))).tolist())
    cat = catalog_series(closes, "BTC/USDT")
    assert cat, "una caminata con vol 4% diaria debe producir montañas"
    m = cat[0]
    assert {"dur_days", "height_pct", "asym_time", "shape", "tol"} <= set(m)
    assert len(m["shape"]) == 24


def test_twin_conserva_longitud_y_arranque() -> None:
    rng = np.random.default_rng(5)
    closes = _series((100 * np.exp(np.cumsum(rng.normal(0, 0.03, 300)))).tolist())
    tw = synthetic_twin(closes, np.random.default_rng(11))
    assert len(tw) == len(closes)
    assert tw.iloc[0] == closes.iloc[0]
    assert not np.allclose(tw.to_numpy(), closes.to_numpy())
