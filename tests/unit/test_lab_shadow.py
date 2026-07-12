"""Tests del shadow pre-firewall H12 (ext5-h28) — funciones puras, sin GCS.

Cubre: paridad del scoring congelado vs sklearn, la grilla de rebalanceo 28d
(ancla fija + catch-up), el label realizado del universo shadow y la matemática
del track record (fees sobre turnover drifteado, benchmark EW, maduración AUC).
"""

import numpy as np
import pandas as pd
import pytest

from src.lab.shadow_producer import (
    CADENCE_DAYS,
    evaluate,
    realized_labels,
    rebalance_due,
    score_probability,
)

COST = 0.0036 + 0.0010  # FEE_RATE + SLIPPAGE del motor


class TestScoreParity:
    def test_matches_sklearn_pipeline(self):
        """El artefacto JSON (μ/σ/coef/b) reproduce predict_proba exactamente."""
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        rng = np.random.default_rng(7)
        x = pd.DataFrame({"ret_63d": rng.normal(0, 0.3, 400)})
        y = (x["ret_63d"] + rng.normal(0, 0.2, 400) > 0).astype(int)
        scaler = StandardScaler().fit(x)
        clf = LogisticRegression(max_iter=1000, random_state=42).fit(scaler.transform(x), y)
        model = {
            "features": ["ret_63d"],
            "scaler_mean": scaler.mean_.tolist(),
            "scaler_scale": scaler.scale_.tolist(),
            "coef": clf.coef_[0].tolist(),
            "intercept": float(clf.intercept_[0]),
        }
        expected = clf.predict_proba(scaler.transform(x))[:, 1]
        np.testing.assert_allclose(score_probability(model, x), expected, atol=1e-12)

    def test_monotone_in_momentum(self):
        """Coef momentum positivo → p crece con ret_63d (top-5 por p == top-5 por ret)."""
        model = {
            "features": ["ret_63d"],
            "scaler_mean": [0.0],
            "scaler_scale": [0.3],
            "coef": [0.8],
            "intercept": 0.0,
        }
        x = pd.DataFrame({"ret_63d": [-0.5, -0.1, 0.0, 0.2, 0.6]})
        p = score_probability(model, x)
        assert list(p) == sorted(p)
        assert p[2] == pytest.approx(0.5)


class TestRebalanceGrid:
    ANCHOR = pd.Timestamp("2026-07-11")

    def test_first_emission_rebalances(self):
        assert rebalance_due(self.ANCHOR, None, self.ANCHOR) == (True, False, 0)

    def test_hold_between_grid_dates(self):
        d = self.ANCHOR + pd.Timedelta(days=5)
        due, catch_up, period = rebalance_due(self.ANCHOR, self.ANCHOR, d)
        assert (due, catch_up, period) == (False, False, 0)

    def test_due_on_grid_date(self):
        d = self.ANCHOR + pd.Timedelta(days=CADENCE_DAYS)
        assert rebalance_due(self.ANCHOR, self.ANCHOR, d) == (True, False, 1)

    def test_missed_grid_day_catches_up_without_reanchor(self):
        """Día 28 perdido → día 29 rebalancea (catch-up) y el periodo sigue anclado."""
        d = self.ANCHOR + pd.Timedelta(days=CADENCE_DAYS + 1)
        assert rebalance_due(self.ANCHOR, self.ANCHOR, d) == (True, True, 1)
        # tras el catch-up, el siguiente grid date sigue siendo ancla+56
        d2 = self.ANCHOR + pd.Timedelta(days=2 * CADENCE_DAYS)
        assert rebalance_due(self.ANCHOR, d, d2) == (True, False, 2)

    def test_same_period_after_catchup_holds(self):
        last = self.ANCHOR + pd.Timedelta(days=CADENCE_DAYS + 1)
        d = self.ANCHOR + pd.Timedelta(days=CADENCE_DAYS + 10)
        assert rebalance_due(self.ANCHOR, last, d)[0] is False


class TestRealizedLabels:
    def test_top_half_wins(self):
        fwd = {"A": 0.10, "B": 0.05, "C": -0.02, "D": -0.10}
        assert realized_labels(fwd) == {"A": 1, "B": 1, "C": 0, "D": 0}

    def test_ties_deterministic_5050(self):
        fwd = {"A": 0.1, "B": 0.1, "C": 0.0, "D": -0.1}
        labels = realized_labels(fwd)
        assert sum(labels.values()) == 2

    def test_odd_universe(self):
        """n impar: la mitad estricta (rank ≤ n/2) va arriba — 1 de 3."""
        labels = realized_labels({"A": 0.2, "B": 0.0, "C": -0.2})
        assert labels == {"A": 1, "B": 0, "C": 0}


def _entry(date, prices, weights=None, is_rebalance=False, universe=None):
    return {
        "decision_date": date,
        "is_rebalance": is_rebalance,
        "weights": weights or {},
        "prices_mxn": prices,
        "universe": universe or [],
    }


class TestEvaluateTrack:
    def test_two_period_track_with_fees_and_bench(self):
        """100% en A, A sube 10%, B plano: fee de entrada una vez, sin turnover al
        re-rebalancear el mismo peso; bench EW = mitad del movimiento."""
        e0 = _entry("2026-07-11", {"A": 100.0, "B": 100.0}, {"A": 1.0}, True)
        e1 = _entry("2026-08-08", {"A": 110.0, "B": 100.0}, {"A": 1.0}, True)
        r = evaluate([e1, e0])  # orden invertido a propósito: evaluate ordena
        assert r["n_rebalances"] == 2
        v_expected = (1 - COST) * 1.10
        assert r["total_return_pct"] == pytest.approx((v_expected - 1) * 100, abs=0.01)
        bench_expected = (1 - COST) * 1.05
        assert r["bench_return_pct"] == pytest.approx((bench_expected - 1) * 100, abs=0.01)
        assert len(r["periods"]) == 1
        assert r["periods"][0]["net_pct"] == pytest.approx(10.0, abs=0.01)
        assert r["periods"][0]["excess_pct"] == pytest.approx(5.0, abs=0.01)

    def test_full_rotation_pays_turnover(self):
        """Rotar 100% de A a B en el rebalanceo cuesta ~2×COST sobre el valor."""
        e0 = _entry("2026-07-11", {"A": 100.0, "B": 100.0}, {"A": 1.0}, True)
        e1 = _entry("2026-08-08", {"A": 100.0, "B": 100.0}, {"B": 1.0}, True)
        r = evaluate([e0, e1])
        v_expected = (1 - COST) * (1 - 2 * COST)  # entrada + rotación completa
        assert r["total_return_pct"] == pytest.approx((v_expected - 1) * 100, abs=0.01)

    def test_cash_when_no_signal(self):
        """Rebalanceo a pesos vacíos → 100% cash: paga la salida y deja de moverse."""
        e0 = _entry("2026-07-11", {"A": 100.0, "B": 100.0}, {"A": 1.0}, True)
        e1 = _entry("2026-08-08", {"A": 120.0, "B": 100.0}, {}, True)
        e2 = _entry("2026-09-05", {"A": 60.0, "B": 100.0}, {}, True)
        r = evaluate([e0, e1, e2])
        v_expected = (1 - COST) * 1.20 * (1 - COST)  # sube con A, sale, ignora el crash
        assert r["total_return_pct"] == pytest.approx((v_expected - 1) * 100, abs=0.01)

    def test_track_starts_at_first_rebalance(self):
        entries = [
            _entry("2026-07-10", {"A": 100.0}),  # emisión sin rebalanceo (no cuenta)
            _entry("2026-07-11", {"A": 100.0}, {"A": 1.0}, True),
        ]
        r = evaluate(entries)
        assert r["track"][0]["date"] == "2026-07-11"

    def test_empty_ledger(self):
        assert "error" in evaluate([])


class TestEvaluateAuc:
    def _universe(self, ps):
        return [{"symbol": s, "p": p} for s, p in ps.items()]

    def test_perfect_foresight_auc_1(self):
        u = self._universe({"A": 0.9, "B": 0.8, "C": 0.2, "D": 0.1})
        e0 = _entry("2026-07-11", {"A": 100, "B": 100, "C": 100, "D": 100}, {"A": 1.0}, True, u)
        e1 = _entry("2026-08-08", {"A": 120, "B": 110, "C": 95, "D": 90}, {"A": 1.0}, True, u)
        r = evaluate([e0, e1])
        assert r["auc_grid"] == 1.0
        assert r["auc_grid_n"] == 4
        assert r["auc_daily_overlap_n"] == 4  # e1 aún no madura

    def test_inverted_scores_auc_0(self):
        u = self._universe({"A": 0.1, "B": 0.2, "C": 0.8, "D": 0.9})
        e0 = _entry("2026-07-11", {"A": 100, "B": 100, "C": 100, "D": 100}, {"C": 1.0}, True, u)
        e1 = _entry("2026-08-08", {"A": 120, "B": 110, "C": 95, "D": 90}, {"C": 1.0}, True, u)
        assert evaluate([e0, e1])["auc_grid"] == 0.0

    def test_no_auc_before_maturity(self):
        u = self._universe({"A": 0.9, "B": 0.1})
        e0 = _entry("2026-07-11", {"A": 100, "B": 100}, {"A": 1.0}, True, u)
        e1 = _entry("2026-07-20", {"A": 110, "B": 100}, {"A": 1.0}, False, u)
        r = evaluate([e0, e1])
        assert "auc_grid" not in r
        assert r["auc_grid_n"] == 0

    def test_maturity_tolerance_window(self):
        """La emisión a D+30 (≤ D+28+3) madura la entrada de D; a D+35 ya no."""
        u = self._universe({"A": 0.9, "B": 0.1})
        e0 = _entry("2026-07-11", {"A": 100, "B": 100}, {"A": 1.0}, True, u)
        ok = _entry("2026-08-10", {"A": 120, "B": 90}, {"A": 1.0}, False, u)
        assert evaluate([e0, ok])["auc_grid_n"] == 2
        far = _entry("2026-08-15", {"A": 120, "B": 90}, {"A": 1.0}, False, u)
        assert evaluate([e0, far])["auc_grid_n"] == 0


class TestCompleteDays:
    def test_partial_today_excluded_late_run(self):
        """Job corriendo a las 19h UTC: la barra de hoy (parcial) queda fuera."""
        from datetime import UTC, datetime

        from src.lab.shadow_producer import complete_days

        m = pd.DataFrame({"ts": pd.to_datetime(["2026-07-10", "2026-07-11", "2026-07-12"])})
        now = datetime(2026, 7, 12, 19, 0, tzinfo=UTC)
        assert str(complete_days(m, now)["ts"].max().date()) == "2026-07-11"

    def test_yesterday_kept_just_after_midnight(self):
        """A las 00:20 UTC el día de ayer ya está completo y es la decisión."""
        from datetime import UTC, datetime

        from src.lab.shadow_producer import complete_days

        m = pd.DataFrame({"ts": pd.to_datetime(["2026-07-11", "2026-07-12"])})
        now = datetime(2026, 7, 13, 0, 20, tzinfo=UTC)
        assert str(complete_days(m, now)["ts"].max().date()) == "2026-07-12"
