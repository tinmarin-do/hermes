"""Tests Fase F arco H11 — backtest diario MXN: fees por turnover, TP-3%, métricas."""

import numpy as np
import pandas as pd
import pytest

from src.lab.backtest_daily import PPY, StrategyParams, _weights_for_day, run_backtest


def _signals(days: int = 60, ret: float = 0.02, high: float = 0.05) -> pd.DataFrame:
    """Un símbolo, p=0.9 constante, retorno y high forward fijos."""
    ts = pd.date_range("2024-01-01", periods=days, freq="D")
    return pd.DataFrame(
        {
            "ts": ts,
            "symbol": "BTC",
            "p": 0.9,
            "rv_20d": 0.03,
            "fwd_ret_24h_mxn": ret,
            "fwd_high_ret": high,
        }
    )


class TestWeights:
    def test_below_threshold_empty(self):
        day = pd.DataFrame({"p": [0.4], "rv_20d": [0.03]}, index=["BTC"])
        assert _weights_for_day(day, StrategyParams(threshold=0.5)).empty

    def test_inverse_vol_and_normalized(self):
        day = pd.DataFrame({"p": [0.8, 0.8], "rv_20d": [0.02, 0.04]}, index=["BTC", "ETH"])
        w = _weights_for_day(day, StrategyParams())
        assert w.sum() == pytest.approx(1.0)
        assert w["BTC"] == pytest.approx(2 * w["ETH"])  # mitad de vol → doble peso

    def test_top_k(self):
        day = pd.DataFrame({"p": [0.9, 0.8, 0.7], "rv_20d": [0.03] * 3}, index=["A", "B", "C"])
        w = _weights_for_day(day, StrategyParams(top_k=2))
        assert set(w.index) == {"A", "B"}


class TestFeesAndReturns:
    def test_fee_on_turnover_day_one(self):
        """Día 1: w pasa de 0→1 → turnover 1 → costo (fee+slip)·1; días siguientes sin
        cambio de pesos → solo el retorno."""
        p = StrategyParams(fee_rate=0.0036, slippage=0.0010)
        r = run_backtest(_signals(days=40, ret=0.02), p)
        # neto medio ≈ 0.02 − (0.0046/40 días) — el turnover solo pega el día 1
        assert r["mean_daily_net_pct"] == pytest.approx(2.0 - 0.46 / 40, abs=0.01)
        assert r["hit_rate"] == 1.0

    def test_tp_caps_gain_when_high_hits(self):
        """high +5% ≥ TP 3% → la ganancia del día se corta en 3% y se cobra la pata extra."""
        base = run_backtest(_signals(days=40, ret=0.04, high=0.05), StrategyParams())
        tp = run_backtest(_signals(days=40, ret=0.04, high=0.05), StrategyParams(take_profit=0.03))
        assert base["mean_daily_net_pct"] > tp["mean_daily_net_pct"]
        assert tp["mean_daily_net_pct"] == pytest.approx(
            3.0 - 0.46 - 0.46 / 40, abs=0.02
        )  # 3% − pata TP diaria − entrada día 1

    def test_tp_saves_loss_after_spike(self):
        """El día tocó +4% pero cerró −2%: el TP convierte la pérdida en +3%."""
        base = run_backtest(_signals(days=40, ret=-0.02, high=0.04), StrategyParams())
        tp = run_backtest(_signals(days=40, ret=-0.02, high=0.04), StrategyParams(take_profit=0.03))
        assert base["mean_daily_net_pct"] < 0 < tp["mean_daily_net_pct"]

    def test_tp_inert_when_high_below(self):
        """high +1% < TP 3% → variantes idénticas."""
        base = run_backtest(_signals(days=40, ret=0.005, high=0.01), StrategyParams())
        tp = run_backtest(_signals(days=40, ret=0.005, high=0.01), StrategyParams(take_profit=0.03))
        assert base["mean_daily_net_pct"] == pytest.approx(tp["mean_daily_net_pct"])


class TestMetrics:
    def test_needs_30_days(self):
        assert "error" in run_backtest(_signals(days=10), StrategyParams())

    def test_ppy_365(self):
        assert PPY == 365

    def test_sharpe_and_dd_sane(self):
        rng = np.random.default_rng(3)
        sig = _signals(days=200)
        sig["fwd_ret_24h_mxn"] = rng.normal(0.001, 0.02, len(sig))
        sig["fwd_high_ret"] = sig["fwd_ret_24h_mxn"] + 0.01
        r = run_backtest(sig, StrategyParams())
        assert -100 <= r["max_drawdown_pct"] <= 0
        assert 0 <= r["psr_0"] <= 1 and 0 <= r["dsr"] <= 1
