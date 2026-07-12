"""Tests fase NN §7.2 (TTM) — partes puras: contextos, anti-leakage del target, rank."""

import numpy as np
import pandas as pd

from src.lab.ttm_trial import TtmSpec, build_contexts, rank_percentile, target_overlaps

SPEC = TtmSpec(trial_id="t", context=5, forecast=3)


def _panel(days: int = 20, symbols=("BTC", "ETH")) -> pd.DataFrame:
    rows = []
    for k, sym in enumerate(symbols):
        ts = pd.date_range("2024-01-01", periods=days, freq="D")
        close = np.arange(days, dtype=float) + 100 * (k + 1)  # series reconocibles
        rows.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "symbol": sym,
                    "close": close,
                    "y": 1.0,
                    "fwd_ret_24h_mxn": 0.01,
                    "operable": True,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


class TestBuildContexts:
    def test_alignment_context_and_targets(self):
        x, tgt, meta = build_contexts(_panel(days=10, symbols=("BTC",)), SPEC)
        assert x.shape == (6, 5) and tgt.shape == (6, 3) and len(meta) == 6
        # fila 0: contexto = closes[0..4] (100..104), día final ts=2024-01-05
        np.testing.assert_array_equal(x[0], [100, 101, 102, 103, 104])
        assert str(meta.iloc[0]["ts"].date()) == "2024-01-05"
        np.testing.assert_array_equal(tgt[0], [105, 106, 107])  # los 3 futuros
        # última fila: target incompleto → NaN
        assert np.isnan(tgt[-1]).all()
        # el último contexto termina en el último close
        assert x[-1, -1] == meta.iloc[-1]["close"] == 109

    def test_short_symbol_skipped(self):
        panel = pd.concat([_panel(days=10, symbols=("BTC",)), _panel(days=3, symbols=("XX",))])
        _, _, meta = build_contexts(panel, SPEC)
        assert set(meta["symbol"]) == {"BTC"}


class TestTargetOverlaps:
    def test_window_and_tail(self):
        is_val = np.zeros(10, dtype=bool)
        is_val[5] = True  # posición 5 es validación
        out = target_overlaps(is_val, horizon=3)
        # target de i = posiciones i+1..i+3 → tocan la 5 las filas 2,3,4
        assert list(np.flatnonzero(out[:7])) == [2, 3, 4]
        assert out[7:].all()  # cola sin target completo → fuera siempre

    def test_no_val_only_tail_excluded(self):
        out = target_overlaps(np.zeros(6, dtype=bool), horizon=2)
        assert not out[:4].any() and out[4:].all()


class TestRankPercentile:
    def test_per_day_percentile(self):
        sig = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2024-01-01"] * 4 + ["2024-01-02"] * 2),
                "pred_ret": [0.04, 0.01, -0.02, 0.10, -0.5, 0.5],
            }
        )
        p = rank_percentile(sig)
        assert p.iloc[3] == 1.0 and p.iloc[2] == 0.25  # mejor y peor del día 1
        assert p.iloc[4] == 0.5 and p.iloc[5] == 1.0  # día 2 independiente
        assert (p.iloc[:4] > 0.5).sum() == 2  # mitad superior = 2 de 4
