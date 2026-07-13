"""Tests de trend_study §5b — persistencia y prima con series construidas a mano."""

import numpy as np
import pandas as pd
import pytest

from src.lab.trend_study import horizon_frame, study

pytestmark = pytest.mark.unit


def _panel(closes: np.ndarray, symbol: str = "BTC/USDT") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "ts": pd.date_range("2023-01-01", periods=len(closes), freq="D"),
            "close": closes,
        }
    )


def test_tendencia_pura_da_persistencia_alta() -> None:
    """Serie con drift fuerte y ruido chico → persistencia ≈ 1 y prima > 0."""
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(0.01 + rng.normal(0, 0.001, 900)))
    per_h = study(_panel(closes))
    p = per_h["5"]["pooled"]
    assert p["persistence"] > 0.9
    # puro drift: no hay lado down suficiente → la prima no se reporta
    assert "trend_premium_pct" not in p


def test_reversion_pura_da_persistencia_baja() -> None:
    """Zigzag determinista de periodo 2 → el signo SIEMPRE se invierte a H=1."""
    closes = np.array([100.0, 110.0] * 450)
    per_h = study(_panel(closes))
    p = per_h["1"]["pooled"]
    assert p["persistence"] < 0.1
    assert p["trend_premium_pct"] < 0


def test_ventanas_no_solapadas() -> None:
    """El paso h evita el solape: con 900 días y h=10 hay ~89 filas, no ~890."""
    rng = np.random.default_rng(2)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 900)))
    df = horizon_frame(_panel(closes), 10)
    assert 70 <= len(df) <= 90


def test_pocas_observaciones_no_reporta() -> None:
    rng = np.random.default_rng(3)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, 200)))
    per_h = study(_panel(closes))
    assert per_h["126"]["pooled"] == {"n": 0} or "persistence" not in per_h["126"]["pooled"]
