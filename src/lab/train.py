"""Entrenamiento formal H11 (Fase D2/E) — split híbrido 80/20 de la decisión #9.

Corpus de TRAIN/VALIDATION: filas Binance (labels MXN vía FX) — "Binance observa".
Las filas Bitso nativas quedan para el slice de confirmación y el shadow (Fase G,
"Bitso mide"). El slice de confirmación (últ. 15%) JAMÁS se toca aquí.

Métricas en las DOS validaciones (media±σ de los K=5 sorteos por bloques mensuales
purgados + corte temporal puro). Metas vigentes (§9.2 + §10.2): accuracy > 0.55 en
AMBAS (sobre filas etiquetadas; naive = 0.50) + profit factor ≥ 1.5 y exceso vs B&H
> 0 en el holdout + precision@5 reportada. F1 queda por comparabilidad (trials 1-8).
Salidas intradía ±3% RETIRADAS (§10.3: TP y SL enterrados con evidencia).
El backtest corre sobre el corte temporal — el único split que simula el futuro — y
SIEMPRE sobre todas las filas con features válidas (anti-leakage §10.1).
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, run_backtest
from src.lab.dataset import extremes_label, relative_label
from src.lab.features import FEATURE_SET_V1, build_candidates, compute_matrix
from src.lab.splits import Split, hybrid_splits, partitions


@dataclass
class TrialSpec:
    trial_id: str
    model: str = "logistic"  # logistic | lightgbm
    label: str = "abs_1pct"  # abs_1pct (v1) | rel_median (§9.1) | extremes_k5 (§10)
    features: list[str] = field(default_factory=lambda: list(FEATURE_SET_V1))
    threshold: float = 0.5
    top_k: int = 5
    # §10.3: salidas intradía ±3% ENTERRADAS (TP tanda 2, SL tanda 3) — default None;
    # un float lo reactiva SOLO para reproducir trials viejos.
    stop_loss_variant: float | None = None
    params: dict[str, Any] = field(default_factory=dict)
    strategy: dict[str, Any] = field(default_factory=dict)  # extras de StrategyParams
    # H12: horizonte del label EN DÍAS. REGLA EN PIEDRA (DESIGN_H12 §3): la cadencia
    # del backtest — y de producción si el candidato se promueve — ES este horizonte.
    horizon_days: int = 1
    seed: int = 42


def load_panel(horizon_days: int = 1) -> pd.DataFrame:
    """Panel Binance diario con features del catálogo + columnas de backtest.

    Con horizon_days=H la columna `fwd_ret_24h_mxn` se REESCRIBE con el retorno
    forward de H días (close→close compuesto con FX H-días). El nombre `24h` se
    conserva por compatibilidad con dataset/labels/backtest — H12 lo documenta;
    la fuente de verdad del horizonte es TrialSpec.horizon_days.
    """
    panel = gcs.read_parquet("datasets/daily_v1.parquet")
    panel = panel[panel["source"] == "binance"].copy()
    panel["ts"] = pd.to_datetime(panel["ts"])
    fx = gcs.read_parquet("fx/usdmxn.parquet")
    fx["ts"] = pd.to_datetime(fx["date"])
    panel = panel.merge(fx[["ts", "usdmxn"]], on="ts", how="left")
    panel = panel.sort_values(["symbol", "ts"]).reset_index(drop=True)

    g = panel.groupby("symbol", observed=True)
    if horizon_days > 1:
        h = horizon_days
        fwd = g["close"].shift(-h) / g["close"].shift(0) - 1.0
        fx_fwd_h = g["usdmxn"].shift(-h) / g["usdmxn"].shift(0) - 1.0
        panel["fwd_ret_24h_mxn"] = (1 + fwd) * (1 + fx_fwd_h.fillna(0.0)) - 1

    # retornos close→HIGH/LOW del día siguiente (disparaban TP/SL — retirados §10.3;
    # se conservan 1d por compatibilidad de columnas). FX intradía constante (aprox.)
    fwd_high = g["high"].shift(-1) / g["close"].shift(0) - 1.0
    fwd_low = g["low"].shift(-1) / g["close"].shift(0) - 1.0
    r_fx_fwd = g["usdmxn"].pct_change().shift(-1).fillna(0.0)
    panel["fwd_high_ret"] = (1 + fwd_high) * (1 + r_fx_fwd) - 1
    panel["fwd_low_ret"] = (1 + fwd_low) * (1 + r_fx_fwd) - 1
    return panel


def _fit_predict(
    X_tr: pd.DataFrame, y_tr: pd.Series, X_vas: list[pd.DataFrame], spec: TrialSpec
) -> list[np.ndarray]:
    """Entrena UNA vez y predice sobre cada frame de X_vas (mismo modelo)."""
    if spec.model == "logistic":
        scaler = StandardScaler().fit(X_tr)
        clf = LogisticRegression(
            max_iter=1000,
            C=float(spec.params.get("C", 1.0)),
            class_weight=spec.params.get("class_weight"),
            random_state=spec.seed,
        ).fit(scaler.transform(X_tr), y_tr)
        return [np.asarray(clf.predict_proba(scaler.transform(X))[:, 1]) for X in X_vas]
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
        return [np.asarray(booster.predict(X)) for X in X_vas]
    raise ValueError(f"modelo desconocido: {spec.model}")


def _split_metrics(y_true: pd.Series, p: np.ndarray, threshold: float) -> dict[str, float]:
    pred = (p > threshold).astype(int)
    return {
        "accuracy": round(float(accuracy_score(y_true, pred)), 4),
        "f1": round(float(f1_score(y_true, pred, zero_division=0)), 4),
        "precision": round(float(precision_score(y_true, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, pred, zero_division=0)), 4),
        "auc_pr": round(float(average_precision_score(y_true, p)), 4),
        "auc_roc": round(float(roc_auc_score(y_true, p)), 4),
        "pred_rate": round(float(pred.mean()), 4),
    }


def _precision_at_k(sig: pd.DataFrame, k: int = 5) -> float | None:
    """De los k elegidos por p cada día, fracción que quedó en el top-k real."""
    hits, total = 0, 0
    for _, day in sig.groupby("ts"):
        if len(day) < 2 * k + 1:
            continue
        pred = set(day.nlargest(k, "p")["symbol"])
        actual = set(day.nlargest(k, "fwd_ret_24h_mxn")["symbol"])
        hits += len(pred & actual)
        total += k
    return round(hits / total, 4) if total else None


def run_trial(spec: TrialSpec) -> dict[str, Any]:
    panel = load_panel(spec.horizon_days)
    if spec.label == "rel_median":
        panel = relative_label(panel)  # solo agrega/reescribe columnas, mismo orden
    elif spec.label == "extremes_k5":
        panel = extremes_label(panel, k=5)
    elif spec.label != "abs_1pct":
        raise ValueError(f"label desconocido: {spec.label}")
    matrix = compute_matrix(panel, build_candidates())
    for col in ("rv_20d", "fwd_high_ret", "fwd_low_ret", "operable"):
        if col not in matrix.columns:
            matrix[col] = panel[col].values

    dates = pd.DatetimeIndex(matrix["ts"].unique())
    iteration, confirmation = partitions(dates)
    matrix = matrix[matrix["ts"].isin(iteration)]  # confirmación: INTOCABLE
    # base = features válidas (para PUNTUAR); labeled = además con y (para APRENDER).
    # En extremes_k5 la banda media queda en base pero fuera de labeled — el backtest
    # SIEMPRE corre sobre base (anti-leakage §10.1: puntuar solo filas que terminaron
    # extremas sería mirar el futuro).
    matrix = matrix.dropna(subset=[*spec.features, "fwd_ret_24h_mxn"])
    labeled = matrix.dropna(subset=["y"])

    splits: list[Split] = hybrid_splits(iteration, seed=spec.seed, horizon_days=spec.horizon_days)
    block_f1: list[float] = []
    block_acc: list[float] = []
    per_split: dict[str, dict[str, Any]] = {}
    temporal_signals: pd.DataFrame | None = None
    precision_at_5: float | None = None

    for split in splits:
        tr = labeled[labeled["ts"].isin(split.train_dates)]
        va = labeled[labeled["ts"].isin(split.val_dates)]
        if len(tr) < 500 or len(va) < 100:
            per_split[split.name] = {"error": "muestras insuficientes"}
            continue
        if split.name == "temporal_holdout":
            va_all = matrix[matrix["ts"].isin(split.val_dates)]
            p, p_all = _fit_predict(
                tr[spec.features], tr["y"], [va[spec.features], va_all[spec.features]], spec
            )
            temporal_signals = va_all[
                [
                    "ts",
                    "symbol",
                    "rv_20d",
                    "fwd_ret_24h_mxn",
                    "fwd_high_ret",
                    "fwd_low_ret",
                    "operable",
                ]
            ].assign(p=p_all)
            precision_at_5 = _precision_at_k(
                va_all[["ts", "symbol", "fwd_ret_24h_mxn"]].assign(p=p_all)
            )
        else:
            (p,) = _fit_predict(tr[spec.features], tr["y"], [va[spec.features]], spec)
        m = _split_metrics(va["y"], p, spec.threshold)
        per_split[split.name] = m
        if split.name.startswith("block_draw"):
            block_f1.append(m["f1"])
            block_acc.append(m["accuracy"])

    result: dict[str, Any] = {
        "trial_id": spec.trial_id,
        "model": spec.model,
        "label": spec.label,
        "horizon_days": spec.horizon_days,
        "features": spec.features,
        "threshold": spec.threshold,
        "params": spec.params,
        "strategy": spec.strategy,
        "seed": spec.seed,
        "n_rows": int(len(matrix)),
        "f1_blocks_mean": round(float(np.mean(block_f1)), 4) if block_f1 else None,
        "f1_blocks_std": round(float(np.std(block_f1)), 4) if block_f1 else None,
        "f1_temporal": per_split.get("temporal_holdout", {}).get("f1"),
        "acc_blocks_mean": round(float(np.mean(block_acc)), 4) if block_acc else None,
        "acc_blocks_std": round(float(np.std(block_acc)), 4) if block_acc else None,
        "acc_temporal": per_split.get("temporal_holdout", {}).get("accuracy"),
        "precision_at_5": precision_at_5,
        "per_split": per_split,
    }

    if temporal_signals is not None:
        # backtest solo sobre símbolos OPERABLES (delistados entrenan, no operan)
        sig = temporal_signals[temporal_signals["operable"]].copy()
        if spec.horizon_days > 1:
            # REGLA EN PIEDRA (DESIGN_H12 §3): rebalanceo SOLO cada H días — la
            # grilla de decisión del backtest es la cadencia del label, y la de
            # producción si esto se promueve. Bloques no solapados por diseño.
            grid = pd.DatetimeIndex(sorted(sig["ts"].unique()))[:: spec.horizon_days]
            sig = sig[sig["ts"].isin(grid)]
        n_trials = _current_n_trials() + 1
        base = StrategyParams(
            threshold=spec.threshold,
            top_k=spec.top_k,
            horizon_days=spec.horizon_days,
            **spec.strategy,
        )
        result["backtest_base"] = run_backtest(sig, base, n_trials=n_trials)
        if spec.stop_loss_variant is not None:  # retirada por default (§10.3)
            sl = StrategyParams(
                threshold=spec.threshold,
                top_k=spec.top_k,
                stop_loss=spec.stop_loss_variant,
                horizon_days=spec.horizon_days,
                **spec.strategy,
            )
            result["backtest_sl3"] = run_backtest(sig, sl, n_trials=n_trials)

    return result


def _current_n_trials() -> int:
    return len(gcs.list_blobs("experiments/trials/"))
