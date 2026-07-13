"""Tests defense_check §15 — economía por variante, agregación y vara W1-W3."""

import pandas as pd
import pytest

from src.lab.defense_check import (
    aggregate_variant,
    apply_bar,
    variant_economics,
    variant_id,
)
from src.lab.window_check import COST


def _day(rows):
    return pd.DataFrame(
        {
            "p": {s: v[0] for s, v in rows.items()},
            "rv_20d": {s: v[1] for s, v in rows.items()},
            "fwd_ret_24h_mxn": {s: v[2] for s, v in rows.items()},
        }
    )


class TestVariantEconomics:
    DAY = _day({"A": (0.9, 0.03, 0.10), "B": (0.6, 0.03, 0.04), "C": (0.2, 0.03, -0.08)})

    def test_exposure_scales_net_and_cost(self):
        """m=0.5: mitad de exposición → mitad del bruto y mitad del costo; bench intacto."""
        full = variant_economics(self.DAY, threshold=0.5, m=1.0)
        half = variant_economics(self.DAY, threshold=0.5, m=0.5)
        assert half["invested"] == pytest.approx(0.5)
        assert half["net_pct"] == pytest.approx(full["net_pct"] / 2, abs=1e-6)
        assert half["bench_pct"] == full["bench_pct"]

    def test_higher_gate_drops_names(self):
        """Compuerta 0.60: B (p=0.6) ya no pasa (> estricto) — solo queda A."""
        r = variant_economics(self.DAY, threshold=0.60, m=1.0)
        assert r["n_selected"] == 1
        assert r["net_pct"] == pytest.approx((0.10 - COST) * 100, abs=1e-4)

    def test_full_cash_when_gate_blocks_all(self):
        r = variant_economics(self.DAY, threshold=0.95, m=1.0)
        assert r["n_selected"] == 0 and r["net_pct"] == 0.0 and r["invested"] == 0.0


class TestBar:
    def _res(self, net_mean, excess_median, worst_year=0.0):
        return {
            "net_mean": net_mean,
            "excess_median": excess_median,
            "worst_year_net": worst_year,
        }

    BASE = variant_id(0.50, False)

    def test_no_variant_beats_baseline_net(self):
        res = {self.BASE: self._res(2.0, 2.0), variant_id(0.55, False): self._res(1.5, 2.5)}
        v = apply_bar(res, self.BASE)
        assert v["winner"] is None

    def test_w1_filters_edge_losers(self):
        """Variante con más neto pero exceso mediano < 1.0 queda fuera por W1."""
        res = {
            self.BASE: self._res(2.0, 2.0),
            variant_id(0.60, True): self._res(5.0, 0.5),
            variant_id(0.55, True): self._res(3.0, 1.5),
        }
        v = apply_bar(res, self.BASE)
        assert v["winner"] == variant_id(0.55, True)

    def test_w3_tiebreak_by_worst_year(self):
        res = {
            self.BASE: self._res(2.0, 2.0),
            variant_id(0.55, False): self._res(3.0, 1.5, worst_year=-2.0),
            variant_id(0.55, True): self._res(3.0, 1.5, worst_year=-0.5),
        }
        assert apply_bar(res, self.BASE)["winner"] == variant_id(0.55, True)


class TestAggregate:
    def test_by_year_and_worst(self):
        ws = [
            {"t0": "2021-05-01", "net_pct": -4.0, "excess_pct": 1.0, "invested": 1.0},
            {"t0": "2022-05-01", "net_pct": 2.0, "excess_pct": 2.0, "invested": 0.8},
            {"t0": "2022-09-01", "net_pct": 4.0, "excess_pct": -1.0, "invested": 0.6},
        ]
        a = aggregate_variant(ws)
        assert a["by_year_net"] == {2021: -4.0, 2022: 3.0}
        assert a["worst_year_net"] == -4.0
        assert a["net_worst"] == -4.0
        assert a["pct_excess_positive"] == pytest.approx(2 / 3, abs=1e-3)
        assert a["invested_mean"] == pytest.approx(0.8)
