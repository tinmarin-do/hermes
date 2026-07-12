"""Tests Fase C arco H11 — label diario MXN y split híbrido purgado."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.lab.dataset import LABEL_THRESHOLD, _daily_bars, _label_frame
from src.lab.splits import (
    EMBARGO_DAYS,
    K_DRAWS,
    PURGE_DAYS,
    hybrid_splits,
    partitions,
)


def _hourly_fixture(daily_closes: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    """24 velas 1h por día que cierran el día en el close indicado."""
    rows = []
    t0 = datetime.fromisoformat(start)
    for d, close in enumerate(daily_closes):
        for h in range(24):
            ts = t0 + timedelta(days=d, hours=h)
            px = close if h == 23 else close * 0.999
            rows.append({"ts": ts, "open": px, "high": px, "low": px, "close": px, "volume": 1.0})
    return pd.DataFrame(rows)


class TestDailyBarsAndLabel:
    def test_resample_daily_close_is_last_hour(self):
        bars = _daily_bars(_hourly_fixture([100.0, 105.0, 103.0]))
        assert len(bars) == 3
        assert bars["close"].tolist() == [100.0, 105.0, 103.0]

    def test_label_native_over_threshold(self):
        # 100→102 = +2% (y=1) · 102→102.5 ≈ +0.49% (y=0); el último día no tiene forward
        bars = _daily_bars(_hourly_fixture([100.0, 102.0, 102.5]))
        out = _label_frame(bars, fx_ret=None)
        assert out["y"].tolist() == [1.0, 0.0]

    def test_label_just_below_threshold_is_negative(self):
        # +0.99% < umbral → y=0 (el caso exactamente-1.00% es inmaterial con floats)
        bars = _daily_bars(_hourly_fixture([100.0, 100.99]))
        out = _label_frame(bars, fx_ret=None)
        assert out["y"].tolist() == [0.0]
        assert LABEL_THRESHOLD == 0.01

    def test_label_fx_conversion_flips_verdict(self):
        # +0.6% en USDT pero +0.6% del peso→ (1.006)(1.006)−1 ≈ +1.2% MXN → y=1
        bars = _daily_bars(_hourly_fixture([100.0, 100.6, 100.6]))
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        # el FX se mueve D1→D2 (mismo periodo que el label del día 1)
        fx = pd.Series([17.0, 17.102, 17.102], index=dates)
        out = _label_frame(bars, fx_ret=fx.pct_change())
        assert out["y"].tolist()[0] == 1.0

    def test_sparse_days_dropped(self):
        df = _hourly_fixture([100.0, 101.0])
        df = df[~((df.ts >= "2024-01-02") & (df.ts < "2024-01-02 12:00"))]  # día 2 con 12 velas
        bars = _daily_bars(df)
        assert len(bars) == 1  # el día incompleto (<20 velas) se descarta


class TestHybridSplits:
    def setup_method(self):
        self.dates = pd.date_range("2021-01-01", "2025-12-31", freq="D")

    def test_partitions_confirmation_is_last_15pct(self):
        iteration, confirmation = partitions(self.dates)
        assert confirmation.min() > iteration.max()
        assert abs(len(confirmation) / len(self.dates) - 0.15) < 0.01

    def test_k_draws_plus_temporal(self):
        splits = hybrid_splits(self.dates, seed=7)
        names = [s.name for s in splits]
        assert len([n for n in names if n.startswith("block_draw")]) == K_DRAWS
        assert "temporal_holdout" in names

    def test_canary_no_train_date_inside_purge_embargo(self):
        """Anti-leakage: ningún día de train dentro de [val−purga, val+embargo]."""
        for split in hybrid_splits(self.dates, seed=7):
            val = pd.Series(split.val_dates)
            blocks = (val.diff() > pd.Timedelta(days=1)).cumsum()
            for _, block in val.groupby(blocks):
                lo = block.min() - pd.Timedelta(days=PURGE_DAYS)
                hi = block.max() + pd.Timedelta(days=EMBARGO_DAYS)
                inside = (split.train_dates >= lo) & (split.train_dates <= hi)
                assert not inside.any(), f"{split.name}: train dentro de la zona prohibida"

    def test_no_overlap_and_reasonable_sizes(self):
        for split in hybrid_splits(self.dates, seed=7):
            assert len(pd.Index(split.train_dates).intersection(split.val_dates)) == 0
            frac_val = len(split.val_dates) / len(self.dates)
            assert 0.10 <= frac_val <= 0.30, f"{split.name}: val={frac_val:.2%}"

    def test_temporal_holdout_val_is_future(self):
        splits = hybrid_splits(self.dates, seed=7)
        temporal = next(s for s in splits if s.name == "temporal_holdout")
        assert temporal.val_dates.min() > temporal.train_dates.max()

    def test_deterministic_by_seed(self):
        a = hybrid_splits(self.dates, seed=7)
        b = hybrid_splits(self.dates, seed=7)
        for sa, sb in zip(a, b, strict=True):
            assert np.array_equal(sa.val_dates, sb.val_dates)
