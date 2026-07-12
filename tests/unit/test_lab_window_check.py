"""Tests window_check §13 — muestreo de ventanas, purga y economía por ventana."""

import numpy as np
import pandas as pd
import pytest

from src.lab.window_check import (
    COST,
    aggregate,
    sample_windows,
    train_mask,
    window_economics,
)


class TestSampleWindows:
    DATES = pd.date_range("2021-01-01", "2025-06-30", freq="D")

    def test_non_overlapping_and_deterministic(self):
        w1 = sample_windows(self.DATES, target=40, seed=42)
        w2 = sample_windows(self.DATES, target=40, seed=42)
        assert w1 == w2  # determinista
        assert len(w1) == 40
        gaps = np.diff([t.value for t in w1])
        assert (gaps >= pd.Timedelta(days=28).value).all()

    def test_different_seed_different_windows(self):
        assert sample_windows(self.DATES, seed=1) != sample_windows(self.DATES, seed=2)

    def test_short_pool_returns_fewer(self):
        short = pd.date_range("2024-01-01", periods=60, freq="D")
        w = sample_windows(short, target=40)
        assert 1 <= len(w) <= 3  # 60 días no caben 40 ventanas de 28

    def test_sorted_output(self):
        w = sample_windows(self.DATES)
        assert w == sorted(w)


class TestTrainMask:
    def test_excludes_label_overlap_both_sides(self):
        """Purga 28 antes + ventana 28 + embargo 28 después = [t0−28, t0+56] fuera."""
        ts = pd.Series(pd.date_range("2023-01-01", periods=200, freq="D"))
        t0 = pd.Timestamp("2023-04-01")
        kept = ts[train_mask(ts, t0)]
        assert kept[(kept >= "2023-03-04") & (kept <= "2023-05-27")].empty
        assert (kept < "2023-03-04").any() and (kept > "2023-05-27").any()


def _day(rows: dict[str, tuple[float, float, float]]) -> pd.DataFrame:
    """{symbol: (p, rv_20d, fwd_ret)} → frame indexado por symbol."""
    return pd.DataFrame(
        {
            "p": {s: v[0] for s, v in rows.items()},
            "rv_20d": {s: v[1] for s, v in rows.items()},
            "fwd_ret_24h_mxn": {s: v[2] for s, v in rows.items()},
        }
    )


class TestWindowEconomics:
    def test_single_pick_math(self):
        """Un solo símbolo pasa el umbral: neto = fwd − costo; bench = media − costo."""
        day = _day({"A": (0.9, 0.03, 0.10), "B": (0.1, 0.03, 0.02)})
        r = window_economics(day, threshold=0.5, top_k=5)
        assert r["n_selected"] == 1
        assert r["net_pct"] == pytest.approx((0.10 - COST) * 100, abs=1e-6)
        assert r["bench_pct"] == pytest.approx((0.06 - COST) * 100, abs=1e-6)
        assert r["excess_pct"] == pytest.approx(4.0, abs=1e-4)

    def test_cash_when_nothing_passes(self):
        """Nada pasa el umbral → cash (0); el exceso es −bench."""
        day = _day({"A": (0.2, 0.03, 0.10), "B": (0.1, 0.03, 0.10)})
        r = window_economics(day, threshold=0.5, top_k=5)
        assert r["n_selected"] == 0 and r["net_pct"] == 0.0
        assert r["excess_pct"] == pytest.approx(-r["bench_pct"], abs=1e-6)

    def test_inverse_vol_weighting_flows_through(self):
        """Dos picks, mitad de vol = doble peso: neto pondera 2:1."""
        day = _day({"A": (0.8, 0.02, 0.09), "B": (0.8, 0.04, 0.03), "C": (0.1, 0.03, 0.0)})
        r = window_economics(day, threshold=0.5, top_k=5)
        gross = (2 / 3) * 0.09 + (1 / 3) * 0.03
        assert r["net_pct"] == pytest.approx((gross - COST) * 100, abs=1e-4)


class TestAggregate:
    def _windows(self, excesses, years=None):
        years = years or ["2022"] * len(excesses)
        return [{"t0": f"{y}-06-01", "excess_pct": e} for e, y in zip(excesses, years, strict=True)]

    def test_passes_bar(self):
        w = self._windows([1.0, 2.0, -0.5, 3.0], ["2021", "2022", "2023", "2024"])
        a = aggregate(w)
        assert a["verdict"] is True
        assert a["by_year"] == {2021: 1.0, 2022: 2.0, 2023: -0.5, 2024: 3.0}

    def test_fails_on_median(self):
        a = aggregate(self._windows([-1.0, -2.0, 3.0, -0.1]))
        assert a["pass_median"] is False and a["verdict"] is False

    def test_fails_on_catastrophic_year(self):
        w = self._windows([5.0, 5.0, 5.0, -1.5], ["2021", "2022", "2023", "2024"])
        a = aggregate(w)
        assert a["pass_median"] and a["pass_pct_positive"]
        assert a["pass_years"] is False and a["verdict"] is False

    def test_fails_on_pct_positive(self):
        a = aggregate(self._windows([2.0, -0.1, -0.1, 0.5]))  # 50% < 55%
        assert a["pass_pct_positive"] is False and a["verdict"] is False
