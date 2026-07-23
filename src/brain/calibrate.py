"""Risk team calibration — quantitative backtest + LLM validation.

Phase 1: Quantitative backtest (126 weekly points, no LLM, ~11s heuristic / ~30s LightGBM)
  - Simulates trading signals from gold features (heuristic or LightGBM QuantCore)
  - Applies risk guardrails (Kelly, VaR) — purely numeric
  - Evaluates forward outcomes to find optimal guardrail params

Phase 2: LLM validation (top 20 volatile dates, full pipeline, ~9 min)
  - Runs the complete LangGraph pipeline on historical dates
  - Compares LLM-decided risk vs heuristic/model risk vs actual outcome

Usage:
  python -m src.brain.calibrate                        # full run (heuristic)
  python -m src.brain.calibrate --model data/models/quant_core_lgbm.pkl  # use trained LightGBM
  python -m src.brain.calibrate --train-model           # train LightGBM first, then calibrate
  python -m src.brain.calibrate --skip-llm             # quant only
  python -m src.brain.calibrate --concurrency 3        # more parallel LLM
"""

from __future__ import annotations

import asyncio
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.brain.news_verify import apply_news_modifier
from src.data.gold.aggregate import aggregate_at, get_available_period, get_forward_return

# LightGBM quant core — replace heuristic when model is available (§8.7.2)
QUANT_CORE_AVAILABLE = False
try:
    from src.brain.quant_core import QuantCore  # noqa: F401

    QUANT_CORE_AVAILABLE = True
except ImportError:
    pass

REPORT_PATH = Path("docs/calibration_report.md")

FORWARD_PERIODS = 168  # 7 days in 1h candles
VOLLATILITY_TOP_N = 20
GRID_KELLY = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
GRID_LOSS_LIMIT = [0.01, 0.02, 0.03, 0.04, 0.05]
CAPITAL = float(os.environ.get("HERMES_CAPITAL_USD", "1"))

# Heuristic signal quality filters — reduce false positives at source
MIN_CONFIDENCE = 0.25  # floor: below this the signal isn't even worth risk review
MIN_RETURN_ABS = 0.002  # |return| > 0.2% minimum directional move
MAX_GARCH_VOL = 0.08  # reject if annualized vol > 8% (panic / illiquid)
HURST_TREND_MIN = 0.52  # clear trend (was 0.55, too strict)
HURST_MR_MAX = 0.48  # clear mean-reversion (was 0.45)
REGIME_ALLOWED = {"trending", "mean-reverting"}


# ── Quantitative backtest ────────────────────────────────────────────────────


@dataclass
class BacktestPoint:
    ts: datetime
    symbol: str
    regime: str
    regime_conf: float
    hurst: float | None
    garch_vol: float | None
    returns_1h: float | None
    returns_24h: float | None
    heuristic_action: str
    heuristic_confidence: float
    kelly_size: float
    var_ok: bool
    risk_approved: bool
    forward_return: float | None
    profitable: bool | None


@dataclass
class CalibrationMetrics:
    kelly_fraction: float
    daily_loss_limit_pct: float
    total_points: int
    approved: int = 0
    rejected: int = 0
    true_positive: int = 0
    false_positive: int = 0
    true_negative: int = 0
    false_negative: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    approval_rate: float = 0.0
    avg_forward_return_approved: float = 0.0
    avg_forward_return_rejected: float = 0.0
    approved_returns: list[float] = field(default_factory=list)
    rejected_returns: list[float] = field(default_factory=list)


def _heuristic_signal(signal: dict) -> tuple[str, float]:
    """Derive a BUY/SELL/HOLD signal from gold features — quality-filtered.

    Applies 5 layers before emitting a signal:
    1. Regime gate — only trending & mean-reverting (no volatile/random-walk)
    2. Hurst gate — must be clearly trending (>0.55) or mean-reverting (<0.45)
    3. Return magnitude — |ret| must exceed threshold (avoids noise)
    4. Volatility cap — reject if garch vol too high (panic conditions)
    5. Confidence floor — minimum regime_conf × penalty to emit
    """
    regime = signal.get("regime", "volatile")
    features = signal.get("features", {})
    regime_conf = signal.get("regime_conf", 0.5)
    hurst = features.get("hurst")
    ret_24h = features.get("returns_24h")
    ret_1h = features.get("returns_1h")
    garch_vol = features.get("garch_vol")

    if garch_vol is None or garch_vol <= 0:
        garch_vol = 0.0

    # 1. Regime gate
    if regime not in REGIME_ALLOWED:
        return "HOLD", 0.0

    # 2. Hurst gate
    if hurst is not None:
        if regime == "trending" and hurst < HURST_TREND_MIN:
            return "HOLD", 0.0
        if regime == "mean-reverting" and hurst > HURST_MR_MAX:
            return "HOLD", 0.0

    # 3. Return magnitude
    if regime == "trending":
        if ret_24h is None:
            return "HOLD", 0.0
        if ret_24h > MIN_RETURN_ABS:
            action = "BUY"
            conf_base = regime_conf * 0.8
        elif ret_24h < -MIN_RETURN_ABS:
            action = "SELL"
            conf_base = regime_conf * 0.8
        else:
            return "HOLD", 0.0
    else:  # mean-reverting
        if ret_1h is None:
            return "HOLD", 0.0
        if ret_1h < -MIN_RETURN_ABS:
            action = "BUY"  # oversold → bounce up
            conf_base = regime_conf * 0.6
        elif ret_1h > MIN_RETURN_ABS:
            action = "SELL"  # overbought → revert down
            conf_base = regime_conf * 0.6
        else:
            return "HOLD", 0.0

    # 4. Volatility cap — kill signal in panic conditions
    if garch_vol > MAX_GARCH_VOL:
        return "HOLD", 0.0

    # 5. Confidence floor
    vol_penalty = min(garch_vol / MAX_GARCH_VOL, 1.0)
    conf = conf_base * (1.0 - vol_penalty * 0.5)

    if conf < MIN_CONFIDENCE:
        return "HOLD", 0.0

    return action, round(min(conf, 0.95), 3)


def _kelly_size(confidence: float, fraction: float) -> float:
    return round(CAPITAL * confidence * fraction, 2)


def _var_check(garch_vol: float | None, size_usd: float, daily_limit_pct: float) -> bool:
    if garch_vol is None or garch_vol <= 0:
        return True
    var_2sigma = size_usd * garch_vol * 2 * math.sqrt(FORWARD_PERIODS)
    return var_2sigma <= CAPITAL * daily_limit_pct


def _generate_weekly_timestamps(
    symbols: list[str], timeframe: str, freq: str = "W-MON"
) -> list[datetime] | None:
    """Sampling timestamps for backtest/training.

    `freq` is a pandas offset alias. Default "W-MON" (weekly) keeps calibration
    comparable; denser frequencies (e.g. "3D", "D") give the model far more
    training samples. Leakage is controlled by the purge+embargo in the
    walk-forward CV (QuantCore.EMBARGO_PERIODS), not by the sampling stride.
    """
    earliest = None
    latest = None
    for sym in symbols:
        period = get_available_period(sym, timeframe)
        if period is None:
            return None
        if earliest is None or period[0] < earliest:
            earliest = period[0]
        if latest is None or period[1] > latest:
            latest = period[1]
    if earliest is None or latest is None:
        return None

    start = earliest.replace(minute=0, second=0, microsecond=0) + timedelta(days=7)
    end = latest.replace(minute=0, second=0, microsecond=0) - timedelta(days=7)

    stamps = pd.date_range(start=start, end=end, freq=freq)
    return [d.to_pydatetime().replace(tzinfo=UTC) for d in stamps if d.to_pydatetime() >= start]


def _run_point(
    signal: dict, kelly_frac: float, loss_limit: float, quant_core: QuantCore | None = None
) -> BacktestPoint | None:
    if quant_core is not None:
        qs = quant_core.predict(signal, kelly_fraction=kelly_frac)
        action = qs.direction
        conf = qs.confidence
    else:
        action, conf = _heuristic_signal(signal)

    symbol = signal["symbol"]
    ts_str = signal.get("ts", "")
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")) if ts_str else datetime.now(UTC)

    if action == "HOLD":
        return None

    features = signal.get("features", {})
    garch_vol = features.get("garch_vol")

    news_conf, _ = apply_news_modifier(conf, signal, action)
    size = _kelly_size(news_conf, kelly_frac)
    var_ok = _var_check(garch_vol, size, loss_limit)
    approved = size > 0 and var_ok
    if not approved:
        size = 0.0

    fwd_ret = get_forward_return(symbol, "1h", ts, FORWARD_PERIODS)
    profitable = None
    eff_ret = fwd_ret
    if fwd_ret is not None:
        if action == "BUY":
            profitable = fwd_ret > 0
            eff_ret = fwd_ret
        else:
            profitable = fwd_ret < 0
            eff_ret = -fwd_ret

    return BacktestPoint(
        ts=ts,
        symbol=symbol,
        regime=signal.get("regime", "volatile"),
        regime_conf=signal.get("regime_conf", 0.5),
        hurst=features.get("hurst"),
        garch_vol=garch_vol,
        returns_1h=features.get("returns_1h"),
        returns_24h=features.get("returns_24h"),
        heuristic_action=action,
        heuristic_confidence=conf,
        kelly_size=size,
        var_ok=var_ok,
        risk_approved=approved,
        forward_return=eff_ret,
        profitable=profitable,
    )


def _compute_metrics(
    points: list[BacktestPoint], kelly_frac: float, loss_limit: float
) -> CalibrationMetrics:
    m = CalibrationMetrics(
        kelly_fraction=kelly_frac, daily_loss_limit_pct=loss_limit, total_points=len(points)
    )

    for p in points:
        if p.profitable is None:
            continue
        if p.risk_approved:
            m.approved += 1
            if p.profitable:
                m.true_positive += 1
            else:
                m.false_positive += 1
            if p.forward_return is not None:
                m.approved_returns.append(p.forward_return)
        else:
            m.rejected += 1
            if p.profitable:
                m.false_negative += 1
            else:
                m.true_negative += 1
            if p.forward_return is not None:
                m.rejected_returns.append(p.forward_return)

    total = m.true_positive + m.false_positive + m.true_negative + m.false_negative
    if total == 0:
        return m

    m.precision = m.true_positive / max(m.true_positive + m.false_positive, 1)
    m.recall = m.true_positive / max(m.true_positive + m.false_negative, 1)
    m.f1 = 2 * m.precision * m.recall / max(m.precision + m.recall, 0.001)
    m.approval_rate = m.approved / total
    m.avg_forward_return_approved = (
        float(np.mean(m.approved_returns)) if m.approved_returns else 0.0
    )
    m.avg_forward_return_rejected = (
        float(np.mean(m.rejected_returns)) if m.rejected_returns else 0.0
    )
    return m


def quantitative_backtest(
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    model_path: str | None = None,
) -> dict:
    """Phase 1: Quantitative backtest. Uses LightGBM QuantCore if model_path provided.

    Returns results dict with metrics.
    """
    if symbols is None:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    core: QuantCore | None = None
    signal_source = "heuristic"
    if model_path and QUANT_CORE_AVAILABLE:
        core = QuantCore.load(Path(model_path))
        signal_source = f"LightGBM ({model_path})"
    elif model_path and not QUANT_CORE_AVAILABLE:
        print("[calibrate:quant] WARNING: quant_core unavailable, falling back to heuristic")

    stamps = _generate_weekly_timestamps(symbols, timeframe)
    if stamps is None or len(stamps) == 0:
        raise RuntimeError("No data available for backtest")

    print(
        f"[calibrate:quant] {len(stamps)} weekly points over {len(symbols)} symbols  "
        f"| source: {signal_source}"
    )
    print(
        f"[calibrate:quant] grid: Kelly {GRID_KELLY} × loss_limit {GRID_LOSS_LIMIT}"
        f" = {len(GRID_KELLY) * len(GRID_LOSS_LIMIT)} combinations"
    )

    all_points: list[BacktestPoint] = []
    for i, ts in enumerate(stamps):
        if i % 50 == 0:
            print(f"  fetching signals at {ts:%Y-%m-%d} ({i + 1}/{len(stamps)})", flush=True)
        signals = aggregate_at(symbols, timeframe, ts)
        for sig in signals:
            point = _run_point(sig, 0.25, 0.02, quant_core=core)
            if point is not None:
                all_points.append(point)

    tradable = [p for p in all_points if p.heuristic_action != "HOLD"]
    print(f"[calibrate:quant] {len(all_points)} signals, {len(tradable)} with action ≠ HOLD")

    best_metrics: CalibrationMetrics | None = None
    all_metrics: list[CalibrationMetrics] = []
    for kf in GRID_KELLY:
        for ll in GRID_LOSS_LIMIT:
            pts = [_run_point_from_features(p, kf, ll) for p in tradable]
            pts = [p for p in pts if p is not None]
            m = _compute_metrics(pts, kf, ll)
            all_metrics.append(m)
            if best_metrics is None or m.f1 > best_metrics.f1:
                best_metrics = m

    return {
        "total_weekly_points": len(stamps),
        "total_signals_evaluated": len(all_points),
        "tradable_points": len(tradable),
        "best_params": {
            "kelly_fraction": best_metrics.kelly_fraction if best_metrics else 0.25,
            "daily_loss_limit_pct": best_metrics.daily_loss_limit_pct if best_metrics else 0.02,
        },
        "best_metrics": best_metrics.__dict__ if best_metrics else {},
        "all_metrics": [m.__dict__ for m in all_metrics],
        "points": all_points,
    }


def _run_point_from_features(
    point: BacktestPoint, kelly_frac: float, loss_limit: float
) -> BacktestPoint:
    news_conf = point.heuristic_confidence
    size = _kelly_size(news_conf, kelly_frac)
    var_ok = _var_check(point.garch_vol, size, loss_limit)
    approved = size > 0 and var_ok
    return BacktestPoint(
        ts=point.ts,
        symbol=point.symbol,
        regime=point.regime,
        regime_conf=point.regime_conf,
        hurst=point.hurst,
        garch_vol=point.garch_vol,
        returns_1h=point.returns_1h,
        returns_24h=point.returns_24h,
        heuristic_action=point.heuristic_action,
        heuristic_confidence=point.heuristic_confidence,
        kelly_size=size if approved else 0.0,
        var_ok=var_ok,
        risk_approved=approved,
        forward_return=point.forward_return,
        profitable=point.profitable,
    )


# ── Phase 2: LLM validation ─────────────────────────────────────────────────


def _top_volatile_dates(points: list[BacktestPoint], n: int = VOLLATILITY_TOP_N) -> list[datetime]:
    scored = sorted(
        [p for p in points if p.garch_vol is not None],
        key=lambda p: p.garch_vol or 0,
        reverse=True,
    )
    seen: set[str] = set()
    top = []
    for p in scored:
        key = p.ts.strftime("%Y-%m-%d")
        if key not in seen:
            seen.add(key)
            top.append(p.ts)
        if len(top) >= n:
            break
    return top


async def _run_pipeline_at(ts: datetime, symbols: list[str], timeframe: str) -> dict | None:
    """Run full LangGraph pipeline as-of a historical timestamp."""

    def _sync_run() -> dict | None:
        try:
            from src.brain.graph import hermes_graph
            from src.data.gold.aggregate import aggregate_at as ag_at

            signals = ag_at(symbols, timeframe, ts)
            if not signals:
                return None

            initial_state: dict = {
                "run_id": str(uuid.uuid4()),
                "symbols": symbols,
                "timeframe": timeframe,
                "gold_signals": signals,
                "regime_summary": "",
                "analyst_reports": [],
                "bull_argument": "",
                "bear_argument": "",
                "debate_rounds": [],
                "debate_round_count": 0,
                "debate_verdict": "HOLD",
                "debate_confidence": 0.5,
                "trader_decision": {},
                "risk_reports": [],
                "risk_synthesis": "",
                "risk_approved": False,
                "pm_decision": {},
                "messages": [],
            }

            final_state = None
            for _mode, chunk in hermes_graph.stream(initial_state, stream_mode=["values"]):
                final_state = chunk

            if final_state is None:
                return None

            pm = final_state.get("pm_decision", {})
            fwd_ret = None
            sym = pm.get("symbol", "")
            action = pm.get("action", "HOLD")
            if sym and sym != "NONE":
                raw_ret = get_forward_return(sym, timeframe, ts, FORWARD_PERIODS)
                if raw_ret is not None:
                    fwd_ret = -raw_ret if action == "SELL" else raw_ret

            return {
                "ts": ts.isoformat(),
                "verdict": final_state.get("debate_verdict", "HOLD"),
                "confidence": final_state.get("debate_confidence", 0.5),
                "risk_approved": final_state.get("risk_approved", False),
                "pm_action": action,
                "pm_symbol": sym,
                "pm_size": pm.get("size_usd", 0),
                "pm_rationale": pm.get("rationale", "")[:500],
                "risk_reports": final_state.get("risk_reports", []),
                "forward_return": fwd_ret,
            }
        except Exception as exc:
            return {"ts": ts.isoformat(), "error": str(exc)}

    return await asyncio.to_thread(_sync_run)


def llm_validation(
    points: list[BacktestPoint],
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    concurrency: int = 2,
    debate_rounds: int = 1,
) -> list[dict]:
    """Phase 2: LLM validation on top volatile dates with concurrent pipeline runs."""
    if symbols is None:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    dates = _top_volatile_dates(points)
    print(f"[calibrate:llm] {len(dates)} dates selected by volatility")
    print(f"[calibrate:llm] concurrency={concurrency} debate_rounds={debate_rounds}")

    os.environ["DEBATE_ROUNDS"] = str(debate_rounds)

    sem = asyncio.Semaphore(concurrency)

    async def _run_one(ts: datetime) -> dict | None:
        async with sem:
            print(f"  LLM pipeline @ {ts:%Y-%m-%d %H:%M}", flush=True)
            t0 = time.time()
            result = await _run_pipeline_at(ts, symbols, timeframe)
            if result:
                elapsed = time.time() - t0
                result["elapsed_s"] = round(elapsed, 1)
                print(
                    f"    verdict={result.get('verdict')} risk={result.get('risk_approved')} "
                    f"({elapsed:.0f}s)",
                    flush=True,
                )
            else:
                print("    no signals available", flush=True)
            return result

    async def _run_all() -> list[dict]:
        tasks = [_run_one(ts) for ts in dates]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    return asyncio.run(_run_all())


# ── Report generation ────────────────────────────────────────────────────────


def generate_report(quant_result: dict, llm_results: list[dict] | None = None) -> str:
    """Generate a markdown calibration report."""
    best = quant_result.get("best_metrics", {})
    params = quant_result.get("best_params", {})

    lines = [
        "# Risk Team Calibration Report",
        "",
        f"**Generated:** {datetime.now(UTC):%Y-%m-%d %H:%M} UTC",
        "",
        "## Phase 1 — Quantitative Backtest",
        "",
        f"- **Weekly points evaluated:** {quant_result.get('total_weekly_points', 0)}",
        f"- **Tradable signals:** {quant_result.get('tradable_points', 0)}",
        f"- **Total signals:** {quant_result.get('total_signals_evaluated', 0)}",
        "",
        "### Optimal Guardrails",
        "",
        "| Parameter | Value |",
        "|---|---|",
        f"| `HERMES_KELLY_FRACTION` | **{params.get('kelly_fraction', 0.10)}** |",
        f"| `HERMES_DAILY_LOSS_LIMIT_PCT` | **{params.get('daily_loss_limit_pct', 0.02)}** |",
        "",
        "### Performance Metrics (at optimum)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Precision | {best.get('precision', 0):.1%} |",
        f"| Recall | {best.get('recall', 0):.1%} |",
        f"| F1 Score | {best.get('f1', 0):.1%} |",
        f"| Approval rate | {best.get('approval_rate', 0):.1%} |",
        f"| Avg return (approved) | {best.get('avg_forward_return_approved', 0):.2%} |",
        f"| Avg return (rejected) | {best.get('avg_forward_return_rejected', 0):.2%} |",
        f"| True positives | {best.get('true_positive', 0)} |",
        f"| False positives | {best.get('false_positive', 0)} |",
        f"| True negatives | {best.get('true_negative', 0)} |",
        f"| False negatives | {best.get('false_negative', 0)} |",
        "",
        "### Parameter Grid Summary",
        "",
        "| Kelly | Loss Limit | F1 | Precision | Recall | Approval % |",
        "|---|---|---|---|---|---|",
    ]

    for m in quant_result.get("all_metrics", []):
        lines.append(
            f"| {m['kelly_fraction']:.2f} | {m['daily_loss_limit_pct']:.2f} | "
            f"{m['f1']:.1%} | {m['precision']:.1%} | {m['recall']:.1%} | "
            f"{m['approval_rate']:.1%} |"
        )

    if llm_results:
        trades = [
            r
            for r in llm_results
            if r.get("pm_action", "HOLD") != "HOLD" and r.get("pm_symbol", "NONE") != "NONE"
        ]
        total_return = sum((r.get("forward_return") or 0) for r in trades)

        lines.extend(
            [
                "",
                "## Phase 2 — LLM Validation",
                "",
                f"**Dates validated:** {len(llm_results)}",
                f"**Trades executed:** {len(trades)}",
                f"**Total P&L (effective):** {total_return:+.2%}",
                "",
                "| Date | Verdict | Conf | Risk OK | PM Action | PM Symbol | Eff Return |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for r in llm_results:
            ret = r.get("forward_return")
            ret_str = f"{ret:+.2%}" if ret is not None else "—"
            lines.append(
                f"| {r.get('ts', '')[:19]} | {r.get('verdict', '?')} | "
                f"{r.get('confidence', 0):.0%} | "
                f"{'YES' if r.get('risk_approved') else 'NO'} | "
                f"{r.get('pm_action', '?')} | {r.get('pm_symbol', '')} | "
                f"{ret_str} |"
            )

    text = "\n".join(lines)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(text)
    return text


# ── Full pipeline ────────────────────────────────────────────────────────────


def run_calibration(
    symbols: list[str] | None = None,
    timeframe: str = "1h",
    llm_concurrency: int = 2,
    debate_rounds: int = 1,
    skip_llm: bool = False,
    model_path: str | None = None,
    train_model: bool = False,
) -> dict:
    """Run full risk calibration — quant backtest + optional LLM validation."""
    t0 = time.time()

    if train_model and QUANT_CORE_AVAILABLE:
        print("[calibrate] training LightGBM QuantCore ...")
        from src.brain.quant_core import train_and_save

        train_and_save(symbols, timeframe)
        if model_path is None:
            model_path = str(Path("data/models/quant_core_lgbm.pkl"))

    print("=" * 60)
    print("PHASE 1: Quantitative Backtest")
    print("=" * 60)
    quant_result = quantitative_backtest(symbols, timeframe, model_path=model_path)
    t1 = time.time()
    print(f"[calibrate] Phase 1 done in {t1 - t0:.0f}s")

    llm_results = None
    if not skip_llm:
        print("")
        print("=" * 60)
        print("PHASE 2: LLM Validation")
        print("=" * 60)

        from src.brain.cost_meter import (
            estimate_cost_usd,
            persist_run,
            start_run,
        )

        n_dates = len(_top_volatile_dates(quant_result["points"]))
        est_total = round(estimate_cost_usd() * n_dates, 4)
        print(
            f"[cost] estimado LLM de la calibracion: ~${est_total:.4f} USD "
            f"({n_dates} fechas × ~${estimate_cost_usd():.4f}) — "
            f"autorizar via /cost:gate antes de correr"
        )
        meter = start_run(f"calibrate-{datetime.now(UTC):%Y%m%dT%H%M%S}")

        llm_results = llm_validation(
            quant_result["points"],
            symbols,
            timeframe,
            concurrency=llm_concurrency,
            debate_rounds=debate_rounds,
        )
        t2 = time.time()
        print(f"[calibrate] Phase 2 done in {t2 - t1:.0f}s")

        cost = meter.summary()
        persist_run(meter)
        print(
            f"[cost] real LLM calibracion: ${cost['cost_usd']:.4f} USD · "
            f"{cost['total_tokens']:,} tokens · {cost['n_calls']} llamadas"
        )
        print(
            f"[cost] registrar en ledger:  /cost:log "
            f"llm|{datetime.now(UTC):%Y-%m-%d}|calibracion {meter.run_id}|"
            f"{cost['cost_usd']:.4f}|auto"
        )

    generate_report(quant_result, llm_results)
    total = time.time() - t0
    print(f"[calibrate] Total: {total:.0f}s — report: {REPORT_PATH}")

    return {"quant": quant_result, "llm": llm_results, "total_s": round(total, 1)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="hermes-calibrate")
    parser.add_argument(
        "--symbols", default=None, help="comma-separated symbols (default: HERMES_ALLOWED_SYMBOLS)"
    )
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--skip-llm", action="store_true", help="skip Phase 2 (LLM validation)")
    parser.add_argument(
        "--concurrency", type=int, default=2, help="max concurrent LLM pipelines (default: 2)"
    )
    parser.add_argument(
        "--debate-rounds", type=int, default=1, help="debate rounds for LLM validation (default: 1)"
    )
    parser.add_argument(
        "--model", default=None, help="path to trained LightGBM model (replaces heuristic)"
    )
    parser.add_argument(
        "--train-model", action="store_true", help="train LightGBM QuantCore before calibration"
    )
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else None
    run_calibration(
        symbols=symbols,
        timeframe=args.timeframe,
        llm_concurrency=args.concurrency,
        debate_rounds=args.debate_rounds,
        skip_llm=args.skip_llm,
        model_path=args.model,
        train_model=args.train_model,
    )
