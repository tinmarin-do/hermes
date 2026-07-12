"""Tests Fase F arco H11 — backtest diario MXN: fees por turnover, TP-3%, métricas."""

import numpy as np
import pandas as pd
import pytest

from src.lab.backtest_daily import PPY, StrategyParams, _weights_for_day, run_backtest


def _signals(
    days: int = 60, ret: float = 0.02, high: float = 0.05, low: float = -0.01
) -> pd.DataFrame:
    """Un símbolo, p=0.9 constante, retornos forward (close/high/low) fijos."""
    ts = pd.date_range("2024-01-01", periods=days, freq="D")
    return pd.DataFrame(
        {
            "ts": ts,
            "symbol": "BTC",
            "p": 0.9,
            "rv_20d": 0.03,
            "fwd_ret_24h_mxn": ret,
            "fwd_high_ret": high,
            "fwd_low_ret": low,
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


class TestStopLossAndProfitFactor:
    def test_sl_caps_loss_when_low_breaches(self):
        """Cierra −5% pero el low tocó −6%: el SL-3% corta la pérdida en −3% + pata extra."""
        base = run_backtest(_signals(days=40, ret=-0.05, low=-0.06), StrategyParams())
        sl = run_backtest(_signals(days=40, ret=-0.05, low=-0.06), StrategyParams(stop_loss=0.03))
        assert sl["mean_daily_net_pct"] > base["mean_daily_net_pct"]
        assert sl["mean_daily_net_pct"] == pytest.approx(
            -3.0 - 0.46 - 0.46 / 40, abs=0.02
        )  # −3% − pata SL diaria − entrada día 1

    def test_sl_inert_when_low_above(self):
        base = run_backtest(_signals(days=40, low=-0.01), StrategyParams())
        sl = run_backtest(_signals(days=40, low=-0.01), StrategyParams(stop_loss=0.03))
        assert sl["mean_daily_net_pct"] == pytest.approx(base["mean_daily_net_pct"])

    def test_pessimistic_stop_fires_before_tp(self):
        """Día que toca −4% Y +5%: con SL+TP simultáneos manda el stop (§9.3 pesimista)."""
        sig = _signals(days=40, ret=0.04, high=0.05, low=-0.04)
        tp_only = run_backtest(sig, StrategyParams(take_profit=0.03))
        both = run_backtest(sig, StrategyParams(take_profit=0.03, stop_loss=0.03))
        assert both["mean_daily_net_pct"] < 0 < tp_only["mean_daily_net_pct"]
        assert both["mean_daily_net_pct"] == pytest.approx(-3.0 - 0.46 - 0.46 / 40, abs=0.02)

    def test_profit_factor_edges(self):
        all_win = run_backtest(_signals(days=40, ret=0.02), StrategyParams())
        all_loss = run_backtest(_signals(days=40, ret=-0.02), StrategyParams())
        assert all_win["profit_factor"] is None  # sin días perdedores
        assert all_loss["profit_factor"] == 0.0  # sin días ganadores


def _alternating(days: int = 60) -> pd.DataFrame:
    """Dos símbolos, la señal salta de uno al otro cada día; mismo retorno en ambos."""
    rows = []
    for i, ts in enumerate(pd.date_range("2024-01-01", periods=days, freq="D")):
        rows.append(
            {
                "ts": ts,
                "symbol": "BTC",
                "p": 0.9 if i % 2 == 0 else 0.1,
                "rv_20d": 0.03,
                "fwd_ret_24h_mxn": 0.01,
                "fwd_high_ret": 0.012,
            }
        )
        rows.append(
            {
                "ts": ts,
                "symbol": "ETH",
                "p": 0.1 if i % 2 == 0 else 0.9,
                "rv_20d": 0.03,
                "fwd_ret_24h_mxn": 0.01,
                "fwd_high_ret": 0.012,
            }
        )
    return pd.DataFrame(rows)


class TestSmoothingAndBenchmark:
    def test_smoothing_cuts_turnover_and_improves_net(self):
        """Señal que rota 100% a diario: suavizar corta turnover; con el mismo retorno
        en ambos símbolos el bruto es ~igual → el ahorro de fees gana."""
        base = run_backtest(_alternating(), StrategyParams())
        sm = run_backtest(_alternating(), StrategyParams(smooth_alpha=0.33))
        assert sm["avg_turnover"] < base["avg_turnover"] / 3
        assert sm["mean_daily_net_pct"] > base["mean_daily_net_pct"]

    def test_alpha_one_is_identity(self):
        base = run_backtest(_signals(days=40), StrategyParams())
        sm = run_backtest(_signals(days=40), StrategyParams(smooth_alpha=1.0))
        assert sm["mean_daily_net_pct"] == pytest.approx(base["mean_daily_net_pct"])

    def test_benchmark_and_excess(self):
        """Universo de 1 símbolo: el benchmark EW es el mismo activo → exceso ≈ 0."""
        r = run_backtest(_signals(days=40), StrategyParams())
        assert r["benchmark_ew_daily_pct"] == pytest.approx(2.0 - 0.46 / 40, abs=0.01)
        assert r["excess_vs_ew_pct"] == pytest.approx(0.0, abs=0.01)


class TestMetrics:
    def test_needs_30_days(self):
        assert "error" in run_backtest(_signals(days=10), StrategyParams())

    def test_horizon_annualization_and_min_obs(self):
        """H12 §3: mismas observaciones a H=7 → sharpe anualiza con 365/7 (√7 menor);
        el mínimo de observaciones baja a 20 bloques para horizontes > 1d."""
        rng = np.random.default_rng(5)
        sig = _signals(days=40)
        sig["fwd_ret_24h_mxn"] = rng.normal(0.002, 0.02, len(sig))
        r1 = run_backtest(sig, StrategyParams())
        r7 = run_backtest(sig, StrategyParams(horizon_days=7))
        assert r7["sharpe_ann"] == pytest.approx(r1["sharpe_ann"] / np.sqrt(7), abs=0.01)
        assert r7["horizon_days"] == 7
        assert "error" in run_backtest(_signals(days=25), StrategyParams())
        assert "error" not in run_backtest(_signals(days=25), StrategyParams(horizon_days=7))

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
