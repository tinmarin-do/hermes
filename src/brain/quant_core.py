"""Núcleo de decisión cuantitativo — LightGBM + GARCH + Kelly/VaR.

§8.7.2 del PRD: régimen → LightGBM (dirección/edge) → GARCH (sizing) → Risk math.
Fija dirección y tamaño sin LLM. Validado con purged + embargoed walk-forward.

El modelo aprende P(forward_return > 0) sobre features de régimen. En inferencia:
  P > 0.65 → BUY,  P < 0.35 → SELL,  resto → HOLD.
Confianza = |P - 0.5| × 2.  Sizing = capital × kelly_fraction × conf × vol_scalar.
"""

from __future__ import annotations

import math
import os
import pickle
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

MODEL_DIR = Path("data/models")
MODEL_PATH = MODEL_DIR / "quant_core_lgbm.pkl"

CAPITAL = float(os.environ.get("HERMES_CAPITAL_USD", "500"))
FORWARD_PERIODS = 168  # 7 days in 1h candles
PURGE_PERIODS = 500  # GARCH window — longest rolling feature
EMBARGO_PERIODS = 168  # 1 week — avoid forward return leakage

REGIME_MAP = {"trending": "trending", "mean_reverting": "mean-reverting", "random_walk": "volatile"}

FEATURE_COLS = [
    "hurst",
    "garch_vol",
    "spread",
    "returns_1h",
    "returns_24h",
    "regime_trending",
    "regime_mean_reverting",
    "vol_ratio",
    "hurst_strength",
    "momentum_1h",
    "momentum_24h",
]

LGBM_PARAMS = {
    "objective": "binary",
    "metric": "binary_logloss",
    "boosting_type": "gbdt",
    "num_leaves": 15,
    "max_depth": 4,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_data_in_leaf": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "verbose": -1,
    "random_state": 42,
    "num_threads": 2,
}


@dataclass
class QuantSignal:
    """Output of the quant core — deterministic direction + sizing before LLM verification."""

    symbol: str
    direction: str  # BUY | SELL | HOLD
    confidence: float  # 0.0 – 1.0
    raw_probability: float  # P(forward_return > 0)
    size_usd: float
    features_used: dict[str, float] = field(default_factory=dict)
    model_version: str = ""


@dataclass
class PurpleWalkForwardResult:
    """Metrics from one walk-forward fold."""

    ts: datetime
    symbol: str
    prediction: float  # predicted probability
    actual: bool  # actual profitable?
    direction: str
    confidence: float


class QuantCore:
    """LightGBM predictor for trade direction + GARCH-based Kelly sizing.

    Trains with purged + embargoed walk-forward CV on historical silver features.
    Model is serializable — train once, reuse for inference without LLM cost.
    """

    def __init__(self) -> None:
        self.model: lgb.Booster | None = None
        self._version: str = datetime.now(UTC).strftime("%Y%m%d-%H%M")
        self._trained: bool = False

    # ── Feature engineering ────────────────────────────────────────────────

    @staticmethod
    def _features_from_signal(signal: dict[str, Any]) -> dict[str, float]:
        f = signal.get("features", {})
        regime = signal.get("regime", "volatile")
        hurst = f.get("hurst")
        garch_vol = f.get("garch_vol")
        spread = f.get("spread")
        ret_1h = f.get("returns_1h")
        ret_24h = f.get("returns_24h")

        gv = garch_vol if garch_vol and garch_vol > 0 else 0.001
        return {
            "hurst": hurst or 0.5,
            "garch_vol": garch_vol or 0.0,
            "spread": spread or 0.0,
            "returns_1h": ret_1h or 0.0,
            "returns_24h": ret_24h or 0.0,
            "regime_trending": 1.0 if regime == "trending" else 0.0,
            "regime_mean_reverting": 1.0 if regime == "mean-reverting" else 0.0,
            "vol_ratio": abs(ret_24h or 0.0) / gv,
            "hurst_strength": abs((hurst or 0.5) - 0.5),
            "momentum_1h": (ret_1h or 0.0) / gv,
            "momentum_24h": (ret_24h or 0.0) / gv,
        }

    def _build_matrix(
        self,
        signals: list[dict[str, Any]],
        forward_returns: dict[tuple[str, datetime], float | None],
    ) -> tuple[pd.DataFrame, pd.Series, list[dict[str, Any]]]:
        """Build feature matrix X and target y from signals and forward returns."""
        features = [self._features_from_signal(s) for s in signals]
        rows = []
        targets = []
        for i, ft in enumerate(features):
            sig = signals[i]
            ts_str = sig.get("ts", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            key = (sig["symbol"], ts)
            fwd = forward_returns.get(key)
            if fwd is not None:
                rows.append(ft)
                targets.append(fwd > 0)
        if not rows:
            return pd.DataFrame(columns=FEATURE_COLS), pd.Series(dtype=float), []
        X = pd.DataFrame(rows)[FEATURE_COLS]
        y = pd.Series(targets, dtype=float)
        return X, y, features

    # ── Purged + embargoed walk-forward ────────────────────────────────────

    def _build_labels(
        self,
        points: list[dict[str, Any]],
        symbols: list[str],
        timeframe: str,
    ) -> dict[tuple[str, datetime], float | None]:
        """Pre-compute forward returns for all points to avoid repeated DB queries."""
        from src.data.gold.aggregate import get_forward_return

        labels: dict[tuple[str, datetime], float | None] = {}
        for sig in points:
            sym = sig["symbol"]
            ts_str = sig.get("ts", "")
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            labels[(sym, ts)] = get_forward_return(sym, timeframe, ts, FORWARD_PERIODS)
        return labels

    def walk_forward_validate(
        self,
        signals: list[dict[str, Any]],
        symbols: list[str],
        timeframe: str = "1h",
    ) -> list[PurpleWalkForwardResult]:
        """Purged + embargoed walk-forward cross-validation.

        For each test point, trains on all earlier points outside the purge + embargo windows.
        Returns per-point predictions with actual outcomes.
        """
        if len(signals) < 10:
            raise ValueError(f"Need at least 10 signals for walk-forward, got {len(signals)}")

        signals_sorted = sorted(signals, key=lambda s: s.get("ts", ""))
        results: list[PurpleWalkForwardResult] = []

        # Forward return for a (symbol, ts) is fold-invariant — precompute ONCE
        # for all points instead of rebuilding labels per test point (was O(n²)
        # DB queries; now O(n)).
        labels = self._build_labels(signals_sorted, symbols, timeframe)

        for i in range(10, len(signals_sorted)):
            test_sig = signals_sorted[i]
            test_ts_str = test_sig.get("ts", "")
            test_ts = datetime.fromisoformat(test_ts_str.replace("Z", "+00:00"))

            fwd_ret = labels.get((test_sig["symbol"], test_ts))
            if fwd_ret is None:
                continue

            train_signals = []
            for j in range(i):
                prev = signals_sorted[j]
                prev_ts_str = prev.get("ts", "")
                prev_ts = datetime.fromisoformat(prev_ts_str.replace("Z", "+00:00"))
                delta = (test_ts - prev_ts).total_seconds() / 3600
                if delta > (PURGE_PERIODS + EMBARGO_PERIODS):
                    train_signals.append(prev)

            if len(train_signals) < 10:
                continue

            X_train, y_train, _ = self._build_matrix(train_signals, labels)
            if len(X_train) < 10:
                continue

            num_train = len(X_train)
            if num_train >= 50:
                split = int(num_train * 0.8)
                train_ds = lgb.Dataset(X_train.iloc[:split], y_train.iloc[:split])
                valid_ds = lgb.Dataset(
                    X_train.iloc[split:], y_train.iloc[split:], reference=train_ds
                )
                valid_sets: list[lgb.Dataset] | None = [valid_ds]
                callbacks: list[Callable[..., Any]] = [lgb.early_stopping(5), lgb.log_evaluation(0)]
            else:
                train_ds = lgb.Dataset(X_train, y_train)
                valid_sets = None
                callbacks = [lgb.log_evaluation(0)]
            model = lgb.train(
                LGBM_PARAMS,
                train_ds,
                num_boost_round=200,
                valid_sets=valid_sets,
                callbacks=callbacks,
            )

            feat = self._features_from_signal(test_sig)
            X_test = pd.DataFrame([feat])[FEATURE_COLS]
            prob = float(model.predict(X_test)[0])
            direction, confidence = _prob_to_signal(prob)
            results.append(
                PurpleWalkForwardResult(
                    ts=test_ts,
                    symbol=test_sig["symbol"],
                    prediction=prob,
                    actual=fwd_ret > 0,
                    direction=direction,
                    confidence=confidence,
                )
            )

        return results

    # ── Train final model ──────────────────────────────────────────────────

    def train(
        self, signals: list[dict[str, Any]], symbols: list[str], timeframe: str = "1h"
    ) -> QuantCore:
        """Train final LightGBM model on all data. Use walk_forward_validate first for metrics."""
        labels = self._build_labels(signals, symbols, timeframe)
        X, y, _ = self._build_matrix(signals, labels)
        if len(X) < 10:
            raise ValueError(f"Insufficient training data: {len(X)} rows")

        num_total = len(X)
        if num_total >= 50:
            split = int(num_total * 0.8)
            train_ds = lgb.Dataset(X.iloc[:split], y.iloc[:split])
            valid_ds = lgb.Dataset(X.iloc[split:], y.iloc[split:], reference=train_ds)
            valid_sets: list[lgb.Dataset] | None = [valid_ds]
            callbacks: list[Callable[..., Any]] = [lgb.early_stopping(10), lgb.log_evaluation(0)]
        else:
            train_ds = lgb.Dataset(X, y)
            valid_sets = None
            callbacks = [lgb.log_evaluation(0)]
        self.model = lgb.train(
            LGBM_PARAMS,
            train_ds,
            num_boost_round=300,
            valid_sets=valid_sets,
            callbacks=callbacks,
        )
        self._trained = True
        return self

    # ── Predict ────────────────────────────────────────────────────────────

    def predict(self, signal: dict[str, Any], kelly_fraction: float = 0.10) -> QuantSignal:
        """Predict trade signal from a single RegimeSignal dict.

        Returns QuantSignal with direction, confidence, and Kelly-based size.
        Training not required — uses _heuristic_signal if no model loaded.
        """
        feat = self._features_from_signal(signal)
        X = pd.DataFrame([feat])[FEATURE_COLS]

        if self.model is not None:
            prob = float(self.model.predict(X)[0])
            direction, confidence = _prob_to_signal(prob)
        else:
            direction, confidence = _heuristic_signal(signal)

        garch_vol = signal.get("features", {}).get("garch_vol") or 0.0
        size_usd = _kelly_size(confidence, kelly_fraction, garch_vol)
        sym = signal.get("symbol", "UNKNOWN")

        return QuantSignal(
            symbol=sym,
            direction=direction,
            confidence=confidence,
            raw_probability=prob if self.model else 0.5,
            size_usd=size_usd,
            features_used=feat,
            model_version=self._version,
        )

    # ── Persistence ────────────────────────────────────────────────────────

    def save(self, path: Path | None = None) -> Path:
        dest = path or MODEL_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = {"model": self.model, "version": self._version, "trained": self._trained}
        with open(dest, "wb") as f:
            pickle.dump(payload, f)
        return dest

    @classmethod
    def load(cls, path: Path | None = None) -> QuantCore:
        src = path or MODEL_PATH
        with open(src, "rb") as f:
            payload = pickle.load(f)  # noqa: S301
        core = cls()
        core.model = payload["model"]
        core._version = payload.get("version", "unknown")
        core._trained = payload.get("trained", True)
        return core

    def is_trained(self) -> bool:
        return self._trained and self.model is not None

    # ── SHAP explainability ────────────────────────────────────────────────

    def explain(self, signal: dict[str, Any]) -> dict[str, Any]:
        """SHAP feature importance breakdown for a single prediction.

        Returns a dashboard-ready dict with:
          - top_features: list of {feature, shap_value, feature_value} sorted by |impact|
          - waterfall_data: base_value + contributions for waterfall plot
          - prediction: direction, probability, confidence
        """
        if self.model is None:
            return {"error": "No trained model available for SHAP explanation"}

        feat = self._features_from_signal(signal)
        X = pd.DataFrame([feat])[FEATURE_COLS]

        try:
            import shap

            explainer = shap.TreeExplainer(self.model)
            shap_values = explainer.shap_values(X)
            expected_value = explainer.expected_value

            if isinstance(expected_value, np.ndarray):
                expected_value = float(expected_value[0])
            if isinstance(shap_values, list):
                sv = shap_values[1] if len(shap_values) > 1 else shap_values[0]
            else:
                sv = shap_values

            sv_flat = np.array(sv).flatten()
        except Exception:
            return {"error": "SHAP computation failed — model may be too small"}

        prob = float(self.model.predict(X)[0])
        direction, confidence = _prob_to_signal(prob)

        contributions: list[dict[str, Any]] = []
        for i, col in enumerate(FEATURE_COLS):
            if i < len(sv_flat):
                contributions.append(
                    {
                        "feature": col,
                        "shap_value": round(float(sv_flat[i]), 6),
                        "feature_value": round(feat.get(col, 0.0), 6),
                    }
                )

        contributions.sort(key=lambda c: abs(float(c["shap_value"])), reverse=True)
        top_n = min(10, len(contributions))

        return {
            "prediction": {
                "direction": direction,
                "probability": round(prob, 4),
                "confidence": confidence,
            },
            "base_value": round(float(expected_value), 4),
            "top_features": contributions[:top_n],
            "waterfall": [
                {"label": c["feature"], "value": c["shap_value"]} for c in contributions[:top_n]
            ],
            "all_features": contributions,
        }


# ── Helpers ─────────────────────────────────────────────────────────────────


def _prob_to_signal(
    prob: float, buy_threshold: float = 0.65, sell_threshold: float = 0.35
) -> tuple[str, float]:
    """Convert model probability to (direction, confidence)."""
    if prob > buy_threshold:
        return "BUY", round((prob - 0.5) * 2, 4)
    if prob < sell_threshold:
        return "SELL", round((0.5 - prob) * 2, 4)
    return "HOLD", 0.0


def _kelly_size(confidence: float, kelly_fraction: float, garch_vol: float) -> float:
    """Kelly-based position sizing: capital × confidence × fraction, scaled by vol."""
    if garch_vol <= 0:
        return round(CAPITAL * confidence * kelly_fraction, 2)
    vol_scalar = min(1.0, 0.01 / garch_vol)
    return round(CAPITAL * confidence * kelly_fraction * vol_scalar, 2)


def _var_check(garch_vol: float | None, size_usd: float, daily_limit_pct: float) -> bool:
    if garch_vol is None or garch_vol <= 0:
        return True
    var_2sigma = size_usd * garch_vol * 2 * math.sqrt(FORWARD_PERIODS)
    return var_2sigma <= CAPITAL * daily_limit_pct


# ── Heuristic fallback (used when no model is available) ─────────────────────

MIN_CONFIDENCE = 0.25
MIN_RETURN_ABS = 0.002
MAX_GARCH_VOL = 0.08
HURST_TREND_MIN = 0.52
HURST_MR_MAX = 0.48
REGIME_ALLOWED = {"trending", "mean-reverting"}


def _heuristic_signal(signal: dict[str, Any]) -> tuple[str, float]:
    """5-layer quality-filtered heuristic — fallback when LightGBM model is unavailable."""
    regime = signal.get("regime", "volatile")
    features = signal.get("features", {})
    regime_conf = signal.get("regime_conf", 0.5)
    hurst = features.get("hurst")
    ret_24h = features.get("returns_24h")
    ret_1h = features.get("returns_1h")
    garch_vol = features.get("garch_vol")

    if garch_vol is None or garch_vol <= 0:
        garch_vol = 0.0
    if regime not in REGIME_ALLOWED:
        return "HOLD", 0.0
    if hurst is not None:
        if regime == "trending" and hurst < HURST_TREND_MIN:
            return "HOLD", 0.0
        if regime == "mean-reverting" and hurst > HURST_MR_MAX:
            return "HOLD", 0.0
    if regime == "trending":
        if ret_24h is None:
            return "HOLD", 0.0
        if ret_24h > MIN_RETURN_ABS:
            action, conf_base = "BUY", regime_conf * 0.8
        elif ret_24h < -MIN_RETURN_ABS:
            action, conf_base = "SELL", regime_conf * 0.8
        else:
            return "HOLD", 0.0
    else:
        if ret_1h is None:
            return "HOLD", 0.0
        if ret_1h < -MIN_RETURN_ABS:
            action, conf_base = "BUY", regime_conf * 0.6
        elif ret_1h > MIN_RETURN_ABS:
            action, conf_base = "SELL", regime_conf * 0.6
        else:
            return "HOLD", 0.0
    if garch_vol > MAX_GARCH_VOL:
        return "HOLD", 0.0
    vol_penalty = min(garch_vol / MAX_GARCH_VOL, 1.0)
    conf = conf_base * (1.0 - vol_penalty * 0.5)
    if conf < MIN_CONFIDENCE:
        return "HOLD", 0.0
    return action, round(min(conf, 0.95), 3)


# ── Walk-forward metrics ────────────────────────────────────────────────────


def compute_metrics(results: list[PurpleWalkForwardResult]) -> dict[str, Any]:
    """Compute accuracy, precision, recall, F1 from walk-forward results."""
    num = len(results)
    if num == 0:
        return {"n": 0}

    correct = sum(1 for r in results if (r.prediction > 0.5) == r.actual)
    accuracy = correct / num

    tp = sum(1 for r in results if r.prediction > 0.5 and r.actual)
    fp = sum(1 for r in results if r.prediction > 0.5 and not r.actual)
    fn = sum(1 for r in results if r.prediction <= 0.5 and r.actual)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 0.001)

    traded = [r for r in results if r.direction != "HOLD"]
    tradable_rate = len(traded) / num if num > 0 else 0.0
    profitable_trades = [r for r in traded if r.actual]
    trade_win_rate = len(profitable_trades) / len(traded) if traded else 0.0

    return {
        "n": num,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tradable_rate": round(tradable_rate, 4),
        "trade_win_rate": round(trade_win_rate, 4),
    }


# ── Convenience entry point ─────────────────────────────────────────────────


def train_and_save(
    symbols: list[str] | None = None, timeframe: str = "1h", path: Path | None = None
) -> QuantCore:
    """Train a QuantCore model on all available data and save to disk."""
    import os

    from src.brain.calibrate import _generate_weekly_timestamps
    from src.data.gold.aggregate import aggregate_at

    if symbols is None:
        raw = os.environ.get("HERMES_ALLOWED_SYMBOLS", "BTC/USDT,ETH/USDT")
        symbols = [s.strip() for s in raw.split(",")]

    # Sampling stride for training. Default weekly (fast + matches calibration);
    # denser values (e.g. "3D", "D") give many more samples and are statistically
    # valid under the walk-forward purge+embargo, but are currently bottlenecked by
    # aggregate_at performance (per-point DB reopen + news subqueries). Optimize
    # aggregate_at before lowering this. Override via QUANT_TRAIN_FREQ.
    freq = os.environ.get("QUANT_TRAIN_FREQ", "W-MON")
    stamps = _generate_weekly_timestamps(symbols, timeframe, freq=freq)
    if not stamps:
        raise RuntimeError("No timestamps available for training")

    all_signals: list[dict[str, Any]] = []
    for ts in stamps:
        signals = aggregate_at(symbols, timeframe, ts)
        all_signals.extend(signals)

    if len(all_signals) < 10:
        raise RuntimeError(f"Only {len(all_signals)} signals — need ≥ 10 for training")

    print(f"[quant_core] {len(all_signals)} signals from {len(stamps)} points (freq={freq})")

    core = QuantCore()

    results = core.walk_forward_validate(all_signals, symbols, timeframe)
    metrics = compute_metrics(results)
    print(
        f"[quant_core] walk-forward: n={metrics['n']} accuracy={metrics['accuracy']:.3f} "
        f"f1={metrics['f1']:.3f} tradable={metrics['tradable_rate']:.1%} "
        f"win_rate={metrics['trade_win_rate']:.1%}"
    )

    core.train(all_signals, symbols, timeframe)
    saved = core.save(path)
    print(f"[quant_core] model saved → {saved}")
    return core
