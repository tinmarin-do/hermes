"""Portfolio backtest of the §8.8 allocator — equity curve + PSR / Deflated Sharpe.

Anti-overfitting by construction:
- **Purged + embargoed walk-forward:** at each rebalance date the quant model is trained
  ONLY on prior data outside the purge+embargo window (no lookahead). We reuse
  ``QuantCore.walk_forward_validate`` (the same validated loop the accuracy report uses).
- **Non-overlapping periods:** rebalance cadence = the model's forward horizon (weekly,
  7 days) so the per-period return series is serially independent → a valid Sharpe.
- **PSR (Bailey & López de Prado, 2012):** probability the true Sharpe > benchmark, adjusted
  for sample size *and* non-normality (skew/kurtosis). PSR(0) answers "is the edge real?".
- **Deflated Sharpe (DSR):** PSR against a benchmark inflated for the number of strategy
  configurations tried — penalizes selection bias / data snooping directly.

No LLM is invoked ($0): this measures the deterministic quant allocator. The LLM committee
only *reduces or vetoes* (§8.7.2), so this is the upper envelope of deployed behavior — the
backtest runs with ``global_mult = 1.0`` (the brake is not cheaply backtestable).
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from src.brain.agents.allocator import compute_allocations
from src.brain.agents.quant import SHORT_MIN_CONF, _short_confirmed

EULER_MASCHERONI = 0.5772156649015329
PERIODS_PER_YEAR = 52  # weekly rebalance


# ── Normal CDF / inverse CDF (no scipy dependency) ───────────────────────────


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse normal CDF — Acklam's rational approximation (|err| < 1.2e-9)."""
    if not 0.0 < p < 1.0:
        raise ValueError("norm_ppf domain is (0, 1)")
    a = [
        -3.969683028665376e1,
        2.209460984245205e2,
        -2.759285104469687e2,
        1.383577518672690e2,
        -3.066479806614716e1,
        2.506628277459239e0,
    ]
    b = [
        -5.447609879822406e1,
        1.615858368580409e2,
        -1.556989798598866e2,
        6.680131188771972e1,
        -1.328068155288572e1,
    ]
    c = [
        -7.784894002430293e-3,
        -3.223964580411365e-1,
        -2.400758277161838e0,
        -2.549732539343734e0,
        4.374664141464968e0,
        2.938163982698783e0,
    ]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0, 3.754408661907416e0]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


# ── Moments ──────────────────────────────────────────────────────────────────


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def _skew(xs: list[float]) -> float:
    n = len(xs)
    s = _std(xs, ddof=0)
    if s == 0 or n == 0:
        return 0.0
    m = _mean(xs)
    return sum(((x - m) / s) ** 3 for x in xs) / n


def _kurtosis(xs: list[float]) -> float:
    """Non-excess kurtosis (normal = 3.0)."""
    n = len(xs)
    s = _std(xs, ddof=0)
    if s == 0 or n == 0:
        return 3.0
    m = _mean(xs)
    return sum(((x - m) / s) ** 4 for x in xs) / n


# ── Sharpe / PSR / DSR ───────────────────────────────────────────────────────


def sharpe_ratio(returns: list[float]) -> float:
    """Per-period (non-annualized) Sharpe of a return series."""
    s = _std(returns, ddof=1)
    return _mean(returns) / s if s > 0 else 0.0


def psr(returns: list[float], sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true Sharpe > sr_benchmark) given the sample."""
    n = len(returns)
    if n < 2:
        return 0.0
    sr = sharpe_ratio(returns)
    skew = _skew(returns)
    kurt = _kurtosis(returns)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return norm_cdf((sr - sr_benchmark) * math.sqrt(n - 1) / denom)


def deflated_sharpe_benchmark(var_sharpe: float, n_trials: int) -> float:
    """Expected maximum Sharpe under the null across ``n_trials`` independent strategies."""
    if n_trials <= 1 or var_sharpe <= 0:
        return 0.0
    g = EULER_MASCHERONI
    z1 = norm_ppf(1 - 1.0 / n_trials)
    z2 = norm_ppf(1 - 1.0 / (n_trials * math.e))
    return math.sqrt(var_sharpe) * ((1 - g) * z1 + g * z2)


def deflated_sharpe(returns: list[float], n_trials: int, var_sharpe: float | None = None) -> float:
    """DSR — PSR against a benchmark deflated for the number of configurations tried.

    When ``var_sharpe`` is None, uses the asymptotic sampling variance of the Sharpe
    estimate under the null, (1 + sr²/2)/(n-1), as a proxy for the cross-trial dispersion.
    """
    n = len(returns)
    if n < 2:
        return 0.0
    if var_sharpe is None:
        sr = sharpe_ratio(returns)
        var_sharpe = (1 + 0.5 * sr * sr) / (n - 1)
    return psr(returns, deflated_sharpe_benchmark(var_sharpe, n_trials))


def max_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return mdd


# ── Backtest ─────────────────────────────────────────────────────────────────


@dataclass
class BacktestResult:
    n_periods: int
    total_return: float
    ann_return: float
    ann_vol: float
    sharpe_ann: float
    psr_zero: float
    dsr: float
    n_trials: int
    max_drawdown: float
    win_rate: float
    skew: float
    kurtosis: float
    avg_legs: float


def run_portfolio_backtest(
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    freq: str = "W-MON",
    budget: float = 1.0,
    short_cap_pct: float = 0.10,
    n_trials: int = 1,
    until: str | None = None,
    fee_rate: float = 0.0,
) -> tuple[BacktestResult, list[float], list[float], list[str]]:
    """Purged walk-forward portfolio backtest. Returns (metrics, returns, equity, period_ts).

    ``until`` (YYYY-MM-DD) reserves a final holdout: only data strictly before it is used.
    Disciplined iteration runs with ``until=2025-06-28``; the holdout is validated once, at the end.
    """
    from src.brain.quant_core import QuantCore
    from src.data.gold.aggregate import aggregate_at

    if symbols is None:
        symbols = _default_symbols()

    stamps = _iteration_stamps(symbols, timeframe, freq, until)

    all_signals: list[dict[str, Any]] = []
    for ts in stamps:
        all_signals.extend(aggregate_at(symbols, timeframe, ts))
    if len(all_signals) < 10:
        raise RuntimeError(f"Only {len(all_signals)} signals — need ≥ 10")

    sig_by_key = {(s["symbol"], s.get("ts", "")): s for s in all_signals}

    # OOS predictions per (symbol, ts) via the validated purged+embargoed loop.
    core = QuantCore()
    results = core.walk_forward_validate(all_signals, symbols, timeframe)

    # Group OOS predictions by timestamp → build the per-date quant_signals vector.
    by_ts: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        ts_iso = r.ts.isoformat()
        sig = sig_by_key.get((r.symbol, ts_iso)) or _find_signal(sig_by_key, r.symbol, r.ts)
        if sig is None:
            continue
        direction, confidence = r.direction, r.confidence
        if direction == "SELL" and (confidence < SHORT_MIN_CONF or not _short_confirmed(sig)):
            direction, confidence = "HOLD", 0.0
        by_ts.setdefault(ts_iso, []).append(
            {
                "symbol": r.symbol,
                "direction": direction,
                "confidence": confidence,
                "garch_vol": (sig.get("features", {}).get("garch_vol")) or 0.0,
                "_ts": r.ts,
            }
        )

    return _evaluate(by_ts, timeframe, budget, short_cap_pct, n_trials, fee_rate)


def _default_symbols() -> list[str]:
    raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
    return [s.strip() for s in raw.split(",")]


def _iteration_stamps(
    symbols: list[str], timeframe: str, freq: str, until: str | None, since: str | None = None
) -> list[datetime]:
    """Rebalance stamps within a window: iteration (``until``) or holdout (``since``).

    ``until`` keeps data strictly before it (iteration); ``since`` keeps data at/after it
    (holdout 2025-06-28→). They can combine to bound an arbitrary range.
    """
    from src.brain.calibrate import _generate_weekly_timestamps

    stamps = _generate_weekly_timestamps(symbols, timeframe, freq=freq)
    if not stamps:
        raise RuntimeError("No timestamps available for backtest")
    tz = stamps[0].tzinfo

    def _cut(s: str) -> datetime:
        c = datetime.fromisoformat(s)
        return c.replace(tzinfo=tz) if (tz is not None and c.tzinfo is None) else c

    if since:
        sc = _cut(since)
        stamps = [s for s in stamps if s >= sc]
    if until:
        uc = _cut(until)
        stamps = [s for s in stamps if s < uc]
    if len(stamps) < 10:
        raise RuntimeError(f"Only {len(stamps)} stamps in window [{since}, {until}) — widen it")
    return stamps


def _evaluate(
    by_ts: dict[str, list[dict[str, Any]]],
    timeframe: str,
    budget: float,
    short_cap_pct: float,
    n_trials: int,
    fee_rate: float = 0.0,
) -> tuple[BacktestResult, list[float], list[float], list[str]]:
    """Given per-date quant signals, run the allocator + realize forward returns → metrics.

    Shared by every strategy (LightGBM, momentum, …) so they're compared on identical
    plumbing: same allocator, same forward-return horizon, same PSR/DSR. ``fee_rate`` charges
    a round-trip transaction cost per period (enter+exit) proportional to gross exposure.
    Returns (metrics, per-period returns, equity curve, per-period ISO timestamps).
    """
    from src.brain.quant_core import FORWARD_PERIODS
    from src.data.gold.aggregate import get_forward_return

    returns: list[float] = []
    leg_counts: list[int] = []
    period_ts: list[str] = []
    for ts_iso, qsigs in sorted(by_ts.items()):
        legs = compute_allocations(qsigs, [], budget, global_mult=1.0, short_cap_pct=short_cap_pct)
        active = [a for a in legs if a["action"] != "HOLD" and abs(a["target_usd"]) > 0]
        if not active:
            continue
        ref_ts = qsigs[0]["_ts"]
        port_ret = 0.0
        gross = 0.0
        for leg in active:
            fwd = get_forward_return(leg["symbol"], timeframe, ref_ts, FORWARD_PERIODS)
            if fwd is None:
                continue
            weight = leg["target_usd"] / budget  # signed fraction of budget
            port_ret += weight * fwd
            gross += abs(weight)
        # round-trip cost: every period we enter (and the next period re-allocates from scratch)
        port_ret -= fee_rate * 2.0 * gross
        returns.append(port_ret)
        leg_counts.append(len(active))
        period_ts.append(ts_iso)

    if len(returns) < 2:
        raise RuntimeError(f"Only {len(returns)} tradable periods — not enough for statistics")

    equity = [1.0]
    for pr in returns:
        equity.append(equity[-1] * (1 + pr))

    ann = math.sqrt(PERIODS_PER_YEAR)
    sr_period = sharpe_ratio(returns)
    res = BacktestResult(
        n_periods=len(returns),
        total_return=round(equity[-1] - 1.0, 4),
        ann_return=round(_mean(returns) * PERIODS_PER_YEAR, 4),
        ann_vol=round(_std(returns) * ann, 4),
        sharpe_ann=round(sr_period * ann, 4),
        psr_zero=round(psr(returns, 0.0), 4),
        dsr=round(deflated_sharpe(returns, n_trials), 4),
        n_trials=n_trials,
        max_drawdown=round(max_drawdown(equity), 4),
        win_rate=round(sum(1 for pr in returns if pr > 0) / len(returns), 4),
        skew=round(_skew(returns), 4),
        kurtosis=round(_kurtosis(returns), 4),
        avg_legs=round(sum(leg_counts) / len(leg_counts), 2),
    )
    return res, returns, equity, period_ts


# ── H5: momentum control (no ML) ──────────────────────────────────────────────

MOM_SCALE = 0.20  # un movimiento de 20% en el lookback → confianza máxima (fijo a priori)


def _past_return(symbol: str, timeframe: str, ts: datetime, periods: int) -> float | None:
    """Trailing return over ``periods`` candles ending at ts (uses only past data)."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        now = con.execute(
            "SELECT close FROM bronze_ohlcv WHERE symbol=? AND timeframe=? AND ts<=? "
            "ORDER BY ts DESC LIMIT 1",
            [symbol, timeframe, ts],
        ).fetchone()
        then = con.execute(
            "SELECT close FROM bronze_ohlcv WHERE symbol=? AND timeframe=? AND ts<=? "
            "ORDER BY ts DESC LIMIT 1",
            [symbol, timeframe, ts - timedelta(hours=periods)],
        ).fetchone()
    finally:
        con.close()
    if not now or not then or not then[0]:
        return None
    return float(now[0]) / float(then[0]) - 1.0


def run_momentum_backtest(
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    freq: str = "W-MON",
    budget: float = 1.0,
    short_cap_pct: float = 0.10,
    n_trials: int = 1,
    until: str | None = None,
    lookback: int = 720,
    fee_rate: float = 0.0,
) -> tuple[BacktestResult, list[float], list[float], list[str]]:
    """H5 control: trivial momentum signal (sign of trailing return) through the SAME allocator.

    If this matches or beats the LightGBM backtest, the ML adds no edge. ``lookback`` is fixed
    a priori (720h = 30d) — not tuned. No model training, no LLM ($0).
    """
    from src.data.gold.aggregate import aggregate_at

    if symbols is None:
        symbols = _default_symbols()
    stamps = _iteration_stamps(symbols, timeframe, freq, until)

    by_ts: dict[str, list[dict[str, Any]]] = {}
    for ts in stamps:
        gv = {
            s["symbol"]: (s.get("features", {}).get("garch_vol") or 0.0)
            for s in aggregate_at(symbols, timeframe, ts)
        }
        for sym in symbols:
            pr = _past_return(sym, timeframe, ts, lookback)
            if pr is None or pr == 0:
                continue
            direction = "BUY" if pr > 0 else "SELL"
            conf = round(min(abs(pr) / MOM_SCALE, 0.95), 4)
            by_ts.setdefault(ts.isoformat(), []).append(
                {
                    "symbol": sym,
                    "direction": direction,
                    "confidence": conf,
                    "garch_vol": gv.get(sym, 0.0),
                    "_ts": ts,
                }
            )

    return _evaluate(by_ts, timeframe, budget, short_cap_pct, n_trials, fee_rate)


# ── H6: multi-scale momentum rule (no ML) ─────────────────────────────────────

MULTISCALE_LOOKBACKS = (168, 336, 720, 2160)  # 7d / 14d / 30d / 90d (fijo a priori)


def run_multiscale_momentum_backtest(
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    freq: str = "W-MON",
    budget: float = 1.0,
    short_cap_pct: float = 0.10,
    n_trials: int = 1,
    until: str | None = None,
    lookbacks: tuple[int, ...] = MULTISCALE_LOOKBACKS,
    fee_rate: float = 0.0,
    since: str | None = None,
) -> tuple[BacktestResult, list[float], list[float], list[str]]:
    """H6 rule: multi-scale time-series momentum via sign-vote across horizons.

    Each symbol votes +1/−1 per lookback (sign of trailing return); direction = sign of the
    vote sum, confidence = |votes| / valid_scales (unanimity → 1.0). Disagreement across scales
    → HOLD. Robust by design — no per-horizon magnitude scaling to tune. Same allocator, perf 7d.
    """
    from src.data.gold.aggregate import aggregate_at

    if symbols is None:
        symbols = _default_symbols()
    stamps = _iteration_stamps(symbols, timeframe, freq, until, since)

    by_ts: dict[str, list[dict[str, Any]]] = {}
    for ts in stamps:
        gv = {
            s["symbol"]: (s.get("features", {}).get("garch_vol") or 0.0)
            for s in aggregate_at(symbols, timeframe, ts)
        }
        for sym in symbols:
            votes = 0
            valid = 0
            for lb in lookbacks:
                pr = _past_return(sym, timeframe, ts, lb)
                if pr is None:
                    continue
                valid += 1
                votes += 1 if pr > 0 else (-1 if pr < 0 else 0)
            if valid == 0 or votes == 0:
                continue
            by_ts.setdefault(ts.isoformat(), []).append(
                {
                    "symbol": sym,
                    "direction": "BUY" if votes > 0 else "SELL",
                    "confidence": round(min(abs(votes) / valid, 0.95), 4),
                    "garch_vol": gv.get(sym, 0.0),
                    "_ts": ts,
                }
            )

    return _evaluate(by_ts, timeframe, budget, short_cap_pct, n_trials, fee_rate)


# ── H7: logistic momentum, regime-conditioned ────────────────────────────────


def _price_series(symbol: str, timeframe: str) -> tuple[list[Any], list[float]]:
    """Load the full close series once (sorted) for fast as-of momentum lookups."""
    from src.data.db import get_connection

    con = get_connection()
    try:
        rows = con.execute(
            "SELECT ts, close FROM bronze_ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
            [symbol, timeframe],
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows], [float(r[1]) for r in rows]


def _asof(ts_list: list[Any], close_list: list[float], target: Any) -> float | None:
    import bisect

    # bronze ts are tz-naive; stamps are tz-aware UTC → strip tz for a valid comparison.
    if getattr(target, "tzinfo", None) is not None:
        target = target.replace(tzinfo=None)
    i = bisect.bisect_right(ts_list, target) - 1
    return close_list[i] if i >= 0 else None


def run_logistic_backtest(
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    freq: str = "W-MON",
    budget: float = 1.0,
    short_cap_pct: float = 0.10,
    n_trials: int = 8,
    until: str | None = None,
    lookbacks: tuple[int, ...] = MULTISCALE_LOOKBACKS,
    fee_rate: float = 0.0,
) -> tuple[BacktestResult, list[float], list[float], list[str]]:
    """H7: logistic regression on multi-scale momentum + regime conditioners (hurst, garch_vol).

    Hypothesis: a model that conditions momentum on regime ("trust it when trending, cash when
    mean-reverting") beats the naive rule, especially in the decaying 2024-25 stretch. Purged +
    embargoed walk-forward: a fresh logistic trains on past-only data at each test point. No LLM.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    from src.brain.quant_core import EMBARGO_PERIODS, FORWARD_PERIODS, PURGE_PERIODS
    from src.data.gold.aggregate import aggregate_at, get_forward_return

    if symbols is None:
        symbols = _default_symbols()
    stamps = _iteration_stamps(symbols, timeframe, freq, until)

    closes = {s: _price_series(s, timeframe) for s in symbols}

    def _mom(sym: str, ts: Any, lb: int) -> float | None:
        ts_list, cl = closes[sym]
        now = _asof(ts_list, cl, ts)
        then = _asof(ts_list, cl, ts - timedelta(hours=lb))
        return (now / then - 1.0) if (now and then) else None

    # Build (symbol, ts) points with features + label.
    points: list[dict[str, Any]] = []
    for ts in stamps:
        gold = {s["symbol"]: s for s in aggregate_at(symbols, timeframe, ts)}
        for sym in symbols:
            g = gold.get(sym)
            if not g:
                continue
            hurst = g["features"].get("hurst")
            gv = g["features"].get("garch_vol")
            moms = [_mom(sym, ts, lb) for lb in lookbacks]
            if hurst is None or gv is None or any(m is None for m in moms):
                continue
            fwd = get_forward_return(sym, timeframe, ts, FORWARD_PERIODS)
            points.append(
                {
                    "symbol": sym,
                    "ts": ts,
                    "feats": [*moms, hurst, gv],
                    "label": (fwd > 0) if fwd is not None else None,
                    "gv": gv,
                }
            )

    points.sort(key=lambda p: p["ts"])
    purge_h = PURGE_PERIODS + EMBARGO_PERIODS
    by_ts: dict[str, list[dict[str, Any]]] = {}

    for i, tp in enumerate(points):
        train_x, train_y = [], []
        for j in range(i):
            pj = points[j]
            if pj["label"] is None:
                continue
            if (tp["ts"] - pj["ts"]).total_seconds() / 3600 > purge_h:
                train_x.append(pj["feats"])
                train_y.append(1 if pj["label"] else 0)
        if len(train_x) < 50 or len(set(train_y)) < 2:
            continue
        scaler = StandardScaler().fit(train_x)
        clf = LogisticRegression(max_iter=300, C=1.0).fit(scaler.transform(train_x), train_y)
        p_up = float(clf.predict_proba(scaler.transform([tp["feats"]]))[0][1])
        if p_up > 0.55:
            direction = "BUY"
        elif p_up < 0.45:
            direction = "SELL"
        else:
            continue
        by_ts.setdefault(tp["ts"].isoformat(), []).append(
            {
                "symbol": tp["symbol"],
                "direction": direction,
                "confidence": round(min(abs(p_up - 0.5) * 2, 0.95), 4),
                "garch_vol": tp["gv"],
                "_ts": tp["ts"],
            }
        )

    return _evaluate(by_ts, timeframe, budget, short_cap_pct, n_trials, fee_rate)


def _find_signal(
    sig_by_key: dict[tuple[str, str], dict[str, Any]], symbol: str, ts: datetime
) -> dict[str, Any] | None:
    """Fallback: ISO timestamp formats may differ slightly; match by symbol + ts prefix."""
    target = ts.isoformat()[:19]
    for (sym, ts_iso), sig in sig_by_key.items():
        if sym == symbol and ts_iso[:19] == target:
            return sig
    return None


if __name__ == "__main__":
    import argparse
    import json

    p = argparse.ArgumentParser(prog="hermes-backtest")
    p.add_argument(
        "--freq", default="W-MON", help="rebalance cadence (default weekly = 7d horizon)"
    )
    p.add_argument("--budget", type=float, default=1.0)
    p.add_argument("--short-cap", type=float, default=0.10)
    p.add_argument("--n-trials", type=int, default=1, help="configs tried, for Deflated Sharpe")
    p.add_argument(
        "--until", default=None, help="holdout cutoff YYYY-MM-DD (iteration uses earlier)"
    )
    p.add_argument(
        "--strategy",
        default="lightgbm",
        choices=["lightgbm", "momentum", "multimom", "logistic"],
    )
    p.add_argument("--mom-lookback", type=int, default=720, help="momentum lookback in candles")
    p.add_argument("--fee", type=float, default=0.0, help="per-side transaction cost (e.g. 0.001)")
    p.add_argument("--timeframe", default="1h")
    args = p.parse_args()

    if args.strategy == "logistic":
        res, rets, equity, _pts = run_logistic_backtest(
            timeframe=args.timeframe,
            freq=args.freq,
            budget=args.budget,
            short_cap_pct=args.short_cap,
            n_trials=args.n_trials,
            until=args.until,
            fee_rate=args.fee,
        )
    elif args.strategy == "multimom":
        res, rets, equity, _pts = run_multiscale_momentum_backtest(
            timeframe=args.timeframe,
            freq=args.freq,
            budget=args.budget,
            short_cap_pct=args.short_cap,
            n_trials=args.n_trials,
            until=args.until,
            fee_rate=args.fee,
        )
    elif args.strategy == "momentum":
        res, rets, equity, _pts = run_momentum_backtest(
            timeframe=args.timeframe,
            freq=args.freq,
            budget=args.budget,
            short_cap_pct=args.short_cap,
            n_trials=args.n_trials,
            until=args.until,
            lookback=args.mom_lookback,
            fee_rate=args.fee,
        )
    else:
        res, rets, equity, _pts = run_portfolio_backtest(
            timeframe=args.timeframe,
            freq=args.freq,
            budget=args.budget,
            short_cap_pct=args.short_cap,
            n_trials=args.n_trials,
            until=args.until,
            fee_rate=args.fee,
        )
    print(json.dumps({"strategy": args.strategy, **asdict(res)}, indent=2))
