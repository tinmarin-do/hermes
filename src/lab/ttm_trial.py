"""Fase NN H12 §7.2 — Config NN-2: TTM (TinyTimeMixers r2) fine-tune → rank → top-5.

Foundation model de series de tiempo (IBM Granite, 805k params) fine-tuneado
sobre los closes diarios del corpus: forecast a 28d → percentil de rank
cross-seccional del día como p → la MISMA regla de decisión de todos los
candidatos (threshold 0.5, top-5, pesos p/rv). Hiperparámetros CONGELADOS en
§7.2 antes de correr; trial contado; regla de cierre pre-registrada (debe
superar al GRU en exceso fase-media Y anti-episodio para seguir vivo).

Anti-leakage doble:
- split híbrido purgado a H=28 (labels), y ADEMÁS
- el target del fine-tune abarca 96d → ventanas de train cuyo objetivo
  [t+1, t+96] toque fechas de validación quedan FUERA del entrenamiento.

Corre como job:  gcloud run jobs execute hermes-lab
  --args="src.lab.ttm_trial,--spec,gs://.../nn2-ttm-h28.json"
"""

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, run_backtest
from src.lab.dataset import extremes_label
from src.lab.splits import hybrid_splits, partitions
from src.lab.train import _current_n_trials, _split_metrics, load_panel


@dataclass
class TtmSpec:
    trial_id: str
    model: str = "ttm_r2"
    label: str = "extremes_k5"
    horizon_days: int = 28
    checkpoint: str = "ibm-granite/granite-timeseries-ttm-r2"
    context: int = 512
    forecast: int = 96
    epochs: int = 3
    lr: float = 5e-4
    batch_size: int = 64
    stride: int = 7
    threshold: float = 0.5
    top_k: int = 5
    seed: int = 42


def target_overlaps(is_val: np.ndarray, horizon: int) -> np.ndarray:
    """out[i] = True si alguna de las siguientes `horizon` posiciones (i+1..i+h)
    es de validación O no alcanzan (target incompleto) — esa ventana NO entrena."""
    n = len(is_val)
    out = np.ones(n, dtype=bool)
    if n > horizon:
        w = sliding_window_view(np.asarray(is_val, dtype=bool)[1:], horizon)
        out[: n - horizon] = w.any(axis=1)
    return out


def rank_percentile(sig: pd.DataFrame, col: str = "pred_ret") -> pd.Series:
    """p = percentil de rank cross-seccional POR DÍA (§7.2: forecast → rank)."""
    return sig.groupby("ts")[col].rank(pct=True, method="first")


def build_contexts(
    panel: pd.DataFrame, spec: TtmSpec
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """Panel largo → (X [n, context] closes, T [n, forecast] closes futuros
    (NaN si incompleto), meta alineada 1:1 con el día FINAL del contexto)."""
    panel = panel.sort_values(["symbol", "ts"]).reset_index(drop=True)
    g = panel.groupby("symbol", observed=True)
    ret = g["close"].pct_change()
    panel["rv_20d"] = ret.groupby(panel["symbol"], observed=True).transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    xs: list[np.ndarray] = []
    ts_: list[np.ndarray] = []
    metas: list[pd.DataFrame] = []
    cols = ["ts", "symbol", "y", "fwd_ret_24h_mxn", "rv_20d", "operable", "close"]
    for _, dfg in panel.groupby("symbol", observed=True):
        closes = dfg["close"].to_numpy(dtype=np.float32)
        if len(closes) < spec.context:
            continue
        ctx = sliding_window_view(closes, spec.context)  # [m, context]; fila i = día i+ctx−1
        m = len(ctx)
        tgt = np.full((m, spec.forecast), np.nan, dtype=np.float32)
        for j in range(spec.forecast):
            valid = max(m - j - 1, 0)  # filas con el j-ésimo futuro disponible
            tgt[:valid, j] = closes[spec.context + j : spec.context + j + valid]
        xs.append(ctx)
        ts_.append(tgt)
        metas.append(dfg.iloc[spec.context - 1 :][cols])
    return np.concatenate(xs), np.concatenate(ts_), pd.concat(metas, ignore_index=True)


def _finetune_and_predict(
    x: np.ndarray,
    tgt: np.ndarray,
    train_idx: np.ndarray,
    predict_sets: list[np.ndarray],
    spec: TtmSpec,
) -> list[np.ndarray]:
    """Fine-tune COMPLETO desde el checkpoint (una vez por split) y forecast a 28d.

    Loss en el espacio normalizado del modelo (loc/scale) — escala-invariante
    entre símbolos. Devuelve pred_ret_28 = f[t+28]/close_t − 1 por set."""
    import torch
    from tsfm_public import get_model

    torch.manual_seed(spec.seed)
    model = get_model(spec.checkpoint, context_length=spec.context, prediction_length=spec.forecast)
    opt = torch.optim.Adam(model.parameters(), lr=spec.lr)
    idx = train_idx[:: spec.stride]
    xt = torch.from_numpy(x[idx]).unsqueeze(-1)
    tt = torch.from_numpy(tgt[idx]).unsqueeze(-1)
    gen = torch.Generator().manual_seed(spec.seed)
    model.train()
    for _ in range(spec.epochs):
        perm = torch.randperm(len(xt), generator=gen)
        for i in range(0, len(xt), spec.batch_size):
            b = perm[i : i + spec.batch_size]
            opt.zero_grad()
            out = model(past_values=xt[b])
            loc, scale = out.loc, out.scale
            loss = torch.nn.functional.mse_loss(
                (out.prediction_outputs - loc) / scale, (tt[b] - loc) / scale
            )
            loss.backward()
            opt.step()

    model.eval()
    h = spec.horizon_days
    outs: list[np.ndarray] = []
    with torch.no_grad():
        for pset in predict_sets:
            preds = []
            for i in range(0, len(pset), 512):
                xb = torch.from_numpy(x[pset[i : i + 512]]).unsqueeze(-1)
                f = model(past_values=xb).prediction_outputs[:, h - 1, 0].numpy()
                preds.append(f / x[pset[i : i + 512], -1] - 1.0)
            outs.append(np.concatenate(preds) if preds else np.empty(0, dtype=np.float32))
    return outs


def run_ttm_trial(spec: TtmSpec) -> dict[str, Any]:
    panel = extremes_label(load_panel(spec.horizon_days), k=5)
    x, tgt, meta = build_contexts(panel, spec)

    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(iteration) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x, tgt, meta = x[keep], tgt[keep], meta[keep].reset_index(drop=True)
    labeled_mask = meta["y"].notna().to_numpy()
    full_target = ~np.isnan(tgt).any(axis=1)

    splits = hybrid_splits(iteration, seed=spec.seed, horizon_days=spec.horizon_days)
    block_acc: list[float] = []
    block_auc: list[float] = []
    per_split: dict[str, dict[str, Any]] = {}
    sig_all: pd.DataFrame | None = None
    result: dict[str, Any] = {**asdict(spec), "n_rows": int(len(meta))}

    for split in splits:
        is_val_row = meta["ts"].isin(split.val_dates).to_numpy()
        # anti-leakage §7.2: target de 96d no puede tocar validación (por símbolo)
        overlaps = np.ones(len(meta), dtype=bool)
        for _, grp in meta.groupby("symbol", observed=True):
            pos = grp.index.to_numpy()
            overlaps[pos] = target_overlaps(is_val_row[pos], spec.forecast)
        tr_idx = np.flatnonzero(
            meta["ts"].isin(split.train_dates).to_numpy() & full_target & ~overlaps
        )
        va_idx = np.flatnonzero(labeled_mask & is_val_row)
        if len(tr_idx) < 500 or len(va_idx) < 100:
            per_split[split.name] = {"error": "muestras insuficientes"}
            continue
        if split.name == "temporal_holdout":
            all_idx = np.flatnonzero(is_val_row)
            p_va_raw, p_all_raw = _finetune_and_predict(x, tgt, tr_idx, [va_idx, all_idx], spec)
            sig_all = meta.iloc[all_idx][
                ["ts", "symbol", "rv_20d", "fwd_ret_24h_mxn", "operable"]
            ].assign(pred_ret=p_all_raw)
            sig_all["p"] = rank_percentile(sig_all).to_numpy()
            va_sig = meta.iloc[va_idx][["ts", "symbol", "y"]].assign(pred_ret=p_va_raw)
        else:
            (p_va_raw,) = _finetune_and_predict(x, tgt, tr_idx, [va_idx], spec)
            va_sig = meta.iloc[va_idx][["ts", "symbol", "y"]].assign(pred_ret=p_va_raw)
        va_sig["p"] = rank_percentile(va_sig).to_numpy()
        m = _split_metrics(va_sig["y"], va_sig["p"].to_numpy(), spec.threshold)
        per_split[split.name] = m
        if split.name.startswith("block_draw"):
            block_acc.append(m["accuracy"])
            block_auc.append(m["auc_roc"])
        print(f"  [ttm] {split.name}: acc={m['accuracy']} auc={m['auc_roc']}")

    result |= {
        "acc_blocks_mean": round(float(np.mean(block_acc)), 4) if block_acc else None,
        "auc_blocks_mean": round(float(np.mean(block_auc)), 4) if block_auc else None,
        "acc_temporal": per_split.get("temporal_holdout", {}).get("accuracy"),
        "auc_temporal": per_split.get("temporal_holdout", {}).get("auc_roc"),
        "per_split": per_split,
    }

    if sig_all is not None:
        sig = sig_all[sig_all["operable"]].copy()
        dates_v = sorted(sig["ts"].unique())
        n_trials = _current_n_trials() + 1
        params = StrategyParams(
            threshold=spec.threshold, top_k=spec.top_k, horizon_days=spec.horizon_days
        )
        fases: list[dict[str, Any]] = []
        for off in range(spec.horizon_days):
            grid = pd.DatetimeIndex(dates_v[off :: spec.horizon_days])
            r = run_backtest(sig[sig["ts"].isin(grid)], params, n_trials=n_trials)
            if "error" in r:
                fases.append({"offset": off, "error": r["error"]})
                continue
            f: dict[str, Any] = {
                "offset": off,
                "excess_pct": r["excess_vs_ew_pct"],
                "profit_factor": r["profit_factor"],
                "periods": r["days"],
            }
            ns, bs = r.get("net_series", []), r.get("bench_series", [])
            if ns and bs:
                e = np.asarray(ns) - np.asarray(bs)
                f["exc_sin_top1_pct"] = round(float(np.delete(e, e.argmax()).mean()) * 100, 4)
            fases.append(f)
            if off == 0:
                result["backtest_base"] = r
        ex = np.asarray([f["excess_pct"] for f in fases if "excess_pct" in f])
        pfs = [f["profit_factor"] for f in fases if f.get("profit_factor")]
        est = [f["exc_sin_top1_pct"] for f in fases if "exc_sin_top1_pct" in f]
        result["phase_check"] = {
            "n_fases": int(len(ex)),
            "excess_mean": round(float(ex.mean()), 4) if len(ex) else None,
            "fases_positivas": int((ex > 0).sum()),
            "pf_phase_mean": round(float(np.mean(pfs)), 4) if pfs else None,
            "exc_sin_top1_mean": round(float(np.mean(est)), 4) if est else None,
            "fases_pos_sin_top1": int(sum(1 for v in est if v > 0)),
            "fases": fases,
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Fase NN §7.2 — trial TTM")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    bucket = os.environ["HERMES_RESEARCH_BUCKET"]
    path = args.spec.removeprefix(f"gs://{bucket}/")
    spec = TtmSpec(**json.loads(gcs.bucket().blob(path).download_as_text()))
    print(f"[ttm] trial={spec.trial_id} checkpoint={spec.checkpoint}")
    result = run_ttm_trial(spec)
    result["ran_at"] = datetime.now(UTC).isoformat()
    gcs.upload_json(result, f"experiments/trials/{spec.trial_id}.json")
    pc = result.get("phase_check", {})
    print(
        f"[ttm] {spec.trial_id}: AUC bloques={result.get('auc_blocks_mean')} "
        f"temporal={result.get('auc_temporal')} · exceso fase-media={pc.get('excess_mean')} "
        f"({pc.get('fases_positivas')}/{pc.get('n_fases')}) · "
        f"sin-top1={pc.get('exc_sin_top1_mean')} · PF={pc.get('pf_phase_mean')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
