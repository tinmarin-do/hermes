"""Unit tests for the portfolio backtest statistics — PSR / DSR / Sharpe.

Pure math, no DB/network. We assert known values and the invariants that make PSR a
valid anti-overfitting metric (range, monotonicity in Sharpe and sample size, deflation).
"""

import pytest

from src.brain.backtest import (
    deflated_sharpe,
    deflated_sharpe_benchmark,
    max_drawdown,
    norm_cdf,
    norm_ppf,
    psr,
    sharpe_ratio,
)

pytestmark = pytest.mark.unit


# ── Normal CDF / inverse ──────────────────────────────────────────────────────


def test_norm_cdf_known_values():
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-9)
    assert norm_cdf(1.96) == pytest.approx(0.9750, abs=1e-3)


def test_norm_ppf_roundtrip():
    for p in (0.05, 0.5, 0.975):
        assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-6)


def test_norm_ppf_domain():
    with pytest.raises(ValueError):
        norm_ppf(0.0)


# ── Sharpe ────────────────────────────────────────────────────────────────────


def test_sharpe_zero_variance_is_zero():
    assert sharpe_ratio([0.01, 0.01, 0.01]) == 0.0


def test_sharpe_positive_series():
    assert sharpe_ratio([0.01, 0.02, 0.03, 0.015]) > 0


# ── PSR ───────────────────────────────────────────────────────────────────────


def test_psr_in_unit_interval():
    assert 0.0 <= psr([0.02, -0.01, 0.03, 0.01, -0.005, 0.02]) <= 1.0


def test_psr_zero_sharpe_is_half():
    # media ≈ 0 → Sharpe ≈ 0 → PSR(0) ≈ 0.5
    assert psr([0.01, -0.01, 0.01, -0.01, 0.01, -0.01]) == pytest.approx(0.5, abs=1e-6)


def test_psr_monotonic_in_sharpe():
    weak = psr([0.01, -0.008, 0.012, -0.009, 0.011])
    strong = psr([0.02, 0.015, 0.025, 0.018, 0.022])
    assert strong > weak


def test_psr_grows_with_sample_size():
    base = [0.02, -0.005, 0.018, 0.01, -0.004]
    more = base * 5  # mismo Sharpe, más muestras → más confianza
    assert psr(more) > psr(base)


# ── Deflated Sharpe ───────────────────────────────────────────────────────────


def test_dsr_benchmark_monotonic_in_trials():
    b1 = deflated_sharpe_benchmark(0.05, 2)
    b2 = deflated_sharpe_benchmark(0.05, 50)
    assert 0.0 < b1 < b2


def test_dsr_no_deflation_at_one_trial():
    rets = [0.02, 0.01, 0.025, 0.015, 0.018]
    assert deflated_sharpe(rets, n_trials=1) == pytest.approx(psr(rets, 0.0), abs=1e-9)


def test_dsr_below_psr_with_many_trials():
    rets = [0.02, 0.01, 0.025, 0.015, 0.018, 0.022]
    assert deflated_sharpe(rets, n_trials=20) <= psr(rets, 0.0) + 1e-9


# ── Max drawdown ──────────────────────────────────────────────────────────────


def test_max_drawdown():
    assert max_drawdown([1.0, 1.2, 0.9, 1.1]) == pytest.approx(-0.25, abs=1e-9)
    assert max_drawdown([1.0, 1.1, 1.2]) == pytest.approx(0.0, abs=1e-9)
