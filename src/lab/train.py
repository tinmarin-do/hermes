"""Entrenamiento formal H11 (Fase D2/E) — split híbrido 80/20 de la decisión #9.

Corpus de TRAIN/VALIDATION: filas Binance (labels MXN vía FX) — "Binance observa".
Las filas Bitso nativas quedan para el slice de confirmación y el shadow (Fase G,
"Bitso mide"). El slice de confirmación (últ. 15%) JAMÁS se toca aquí.

F1 se reporta en las DOS validaciones (meta: ≥0.60 en AMBAS):
  · media±σ de los K=5 sorteos por bloques mensuales purgados
  · corte temporal puro (último 20%)
El backtest de estrategia (base + TP-3%) corre sobre el corte temporal — el
único split que simula el futuro de verdad.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, run_backtest
from src.lab.features import FEATURE_SET_V1, build_candidates, compute_matrix
from src.lab.splits import Split, hybrid_splits, partitions


@dataclass
class TrialSpec:
    trial_id: str
    model: str = "logistic"  # logistic | lightgbm
    features: list[str] = field(default_factory=lambda: list(FEATURE_SET_V1))
    threshold: float = 0.5
    top_k: int = 5
    take_profit_variant: float = 0.03  # decisión #10: SIEMPRE se corre la variante
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 42


def load_panel() -> pd.DataFrame:
    """Panel Binance diario con features del catálogo + columnas de backtest."""
    panel = gcs.read_parquet("datasets/daily_v1.parquet")
    panel = panel[panel["source"] == "binance"].copy()
    panel["ts"] = pd.to_datetime(panel["ts"])
    fx = gcs.read_parquet("fx/usdmxn.parquet")
    fx["ts"] = pd.to_datetime(fx["date"])
    panel = panel.merge(fx[["ts", "usdmxn"]], on="ts", how="left")
    panel = panel.sort_values(["symbol", "ts"]).reset_index(drop=True)

    # retorno close→HIGH del día siguiente (dispara el TP-3%); FX del día se asume
    # constante intradía para el trigger (aprox. documentada en DESIGN_H11)
    g = panel.groupby("symbol", observed=True)
    fwd_high = g["high"].shift(-1) / g["close"].shift(0) - 1.0
    r_fx_fwd = g["usdmxn"].pct_change().shift(-1).fillna(0.0)
    panel["fwd_high_ret"] = (1 + fwd_high) * (1 + r_fx_fwd) - 1
    return panel


def _fit_predict(
    X_tr: pd.DataFrame, y_tr: pd.Series, X_va: pd.DataFrame, spec: TrialSpec
) -> np.ndarray:
    if spec.model == "logistic":
        scaler = StandardScaler().fit(X_tr)
        clf = LogisticRegression(
            max_iter=1000,
            C=float(spec.params.get("C", 1.0)),
            class_weight=spec.params.get("class_weight"),
            random_state=spec.seed,
        ).fit(scaler.transform(X_tr), y_tr)
        return np.asarray(clf.predict_proba(scaler.transform(X_va))[:, 1])
    if spec.model == "lightgbm":
        import lightgbm as lgb

        base = {
            "objective": "binary",
            "metric": "binary_logloss",
            "num_leaves": 15,
            "max_depth": 4,
            "learning_rate": 0.05,
            "min_data_in_leaf": 50,
            "lambda_l1": 0.1,
            "lambda_l2": 0.1,
            "verbose": -1,
            "random_state": spec.seed,
        }
        base.update(spec.params)
        booster = lgb.train(base, lgb.Dataset(X_tr, label=y_tr), num_boost_round=300)
        return np.asarray(booster.predict(X_va))
    raise ValueError(f"modelo desconocido: {spec.model}")


def _split_metrics(y_true: pd.Series, p: np.ndarray, threshold: float) -> dict[str, float]:
    pred = (p > threshold).astype(int)
    return {
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "auc_pr": round(float(average_precision_score(y_true, p)), 4),
        "pred_rate": round(float(pred.mean()), 4),
    }


def run_trial(spec: TrialSpec) -> dict[str, Any]:
    panel = load_panel()
    matrix = compute_matrix(panel, build_candidates())
    for col in ("rv_20d", "fwd_high_ret", "operable"):
        if col not in matrix.columns:
            matrix[col] = panel[col].values

    dates = pd.DatetimeIndex(matrix["ts"].unique())
    iteration, confirmation = partitions(dates)
    matrix = matrix[matrix["ts"].isin(iteration)]  # confirmación: INTOCABLE
    matrix = matrix.dropna(subset=[*spec.features, "y", "fwd_ret_24h_mxn"])

    splits: list[Split] = hybrid_splits(iteration, seed=spec.seed)
    block_f1: list[float] = []
    per_split: dict[str, dict[str, Any]] = {}
    temporal_signals: pd.DataFrame | None = None

    for split in splits:
        tr = matrix[matrix["ts"].isin(split.train_dates)]
        va = matrix[matrix["ts"].isin(split.val_dates)]
        if len(tr) < 500 or len(va) < 100:
            per_split[split.name] = {"error": "muestras insuficientes"}
            continue
        p = _fit_predict(tr[spec.features], tr["y"], va[spec.features], spec)
        m = _split_metrics(va["y"], p, spec.threshold)
        per_split[split.name] = m
        if split.name.startswith("block_draw"):
            block_f1.append(m["f1"])
        elif split.name == "temporal_holdout":
            temporal_signals = va[
                ["ts", "symbol", "rv_20d", "fwd_ret_24h_mxn", "fwd_high_ret", "operable"]
            ].assign(p=p)

    result: dict[str, Any] = {
        "trial_id": spec.trial_id,
        "model": spec.model,
        "features": spec.features,
        "threshold": spec.threshold,
        "params": spec.params,
        "seed": spec.seed,
        "n_rows": int(len(matrix)),
        "f1_blocks_mean": round(float(np.mean(block_f1)), 4) if block_f1 else None,
        "f1_blocks_std": round(float(np.std(block_f1)), 4) if block_f1 else None,
        "f1_temporal": per_split.get("temporal_holdout", {}).get("f1"),
        "per_split": per_split,
    }

    if temporal_signals is not None:
        # backtest solo sobre símbolos OPERABLES (delistados entrenan, no operan)
        sig = temporal_signals[temporal_signals["operable"]].copy()
        n_trials = _current_n_trials() + 1
        base = StrategyParams(threshold=spec.threshold, top_k=spec.top_k)
        tp = StrategyParams(
            threshold=spec.threshold, top_k=spec.top_k, take_profit=spec.take_profit_variant
        )
        result["backtest_base"] = run_backtest(sig, base, n_trials=n_trials)
        result["backtest_tp3"] = run_backtest(sig, tp, n_trials=n_trials)

    return result


def _current_n_trials() -> int:
    return len(gcs.list_blobs("experiments/trials/"))
