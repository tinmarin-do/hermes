"""Fase NN H12 §7 — challenger del campeón. Config 1: GRU sobre secuencias OHLCV.

Hipótesis NUEVA (no re-test de capacidad: LGBM ya perdió 3× contra la logística):
cambia el INPUT — en vez de features tabulares diseñadas a mano, la red ve la
secuencia cruda de los últimos `window` días (canales estacionarios derivados del
OHLCV: ret_1d, hl_range, vol_rel) y aprende su propia representación. Label y
metodología IDÉNTICAS al campeón: extremes_k5 H=28, split híbrido purgado a H,
backtest en grilla de 28d, y el phase check completo (M1-M3) DENTRO del trial.

Reglas del pre-registro §7/§7.1:
- Hiperparámetros CONGELADOS antes de correr (sin loops de tuning — 1 config = 1
  trial contado en experiments/trials/). Épocas fijas, sin early-stopping sobre
  validation (sería selección de modelo con el set de evaluación).
- Normalización por-ventana (μ/σ de la propia secuencia): causal por construcción
  — solo usa datos ≤ t.
- Anti-leakage §10.1: el backtest puntúa TODAS las filas con secuencia válida
  (la banda media no etiquetada incluida), no solo las que terminaron extremas.

Corre como job:  gcloud run jobs execute hermes-lab
  --args="src.lab.nn_trial,--spec,gs://.../nn-gru-h28.json"
"""

import argparse
import hashlib
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from src.lab import gcs
from src.lab.backtest_daily import StrategyParams, run_backtest
from src.lab.dataset import extremes_label
from src.lab.splits import hybrid_splits, partitions
from src.lab.train import _current_n_trials, _precision_at_k, _split_metrics, load_panel


@dataclass
class NnSpec:
    trial_id: str
    model: str = "gru_seq"
    label: str = "extremes_k5"
    horizon_days: int = 28
    window: int = 84  # ~1 trimestre de contexto (>= formación ret_63d del campeón)
    channels: list[str] = field(default_factory=lambda: ["ret_1d", "hl_range", "vol_rel"])
    hidden: int = 32
    layers: int = 1
    dropout: float = 0.2
    lr: float = 1e-3
    batch_size: int = 256
    epochs: int = 15
    threshold: float = 0.5
    top_k: int = 5
    seed: int = 42


def _add_channels(panel: pd.DataFrame) -> pd.DataFrame:
    """Canales estacionarios derivados del OHLCV crudo + rv_20d (pesos del backtest).
    Todo causal: rolling/pct_change solo miran hacia atrás."""
    panel = panel.sort_values(["symbol", "ts"]).reset_index(drop=True)
    g = panel.groupby("symbol", observed=True)
    ret = g["close"].pct_change()
    panel["ret_1d"] = ret
    panel["hl_range"] = (panel["high"] - panel["low"]) / panel["close"]
    vol_ma = g["volume"].transform(lambda x: x.rolling(20, min_periods=10).mean())
    panel["vol_rel"] = np.log((panel["volume"] / vol_ma).clip(lower=1e-3))
    panel["rv_20d"] = ret.groupby(panel["symbol"], observed=True).transform(
        lambda x: x.rolling(20, min_periods=10).std()
    )
    return panel


def build_sequences(panel: pd.DataFrame, spec: NnSpec) -> tuple[np.ndarray, pd.DataFrame]:
    """Panel largo → (X [n, window, canales] float32 z-normado por ventana, meta).

    meta (ts, symbol, y, fwd_ret_24h_mxn, rv_20d, operable) alinea 1:1 con X: la
    fila i describe el día FINAL de la secuencia i. Ventanas con NaN quedan fuera.
    """
    panel = _add_channels(panel)
    xs: list[np.ndarray] = []
    metas: list[pd.DataFrame] = []
    cols = ["ts", "symbol", "y", "fwd_ret_24h_mxn", "rv_20d", "operable"]
    for _, dfg in panel.groupby("symbol", observed=True):
        arr = dfg[spec.channels].to_numpy(dtype=np.float32)
        if len(arr) < spec.window:
            continue
        win = sliding_window_view(arr, spec.window, axis=0).transpose(0, 2, 1)
        valid = ~np.isnan(win).any(axis=(1, 2))
        if not valid.any():
            continue
        win = win[valid].copy()
        mu = win.mean(axis=1, keepdims=True)
        sd = win.std(axis=1, keepdims=True) + 1e-8
        xs.append((win - mu) / sd)
        metas.append(dfg.iloc[spec.window - 1 :][cols].iloc[valid])
    x = np.concatenate(xs).astype(np.float32)
    meta = pd.concat(metas, ignore_index=True)
    return x, meta


def _build_net(spec: NnSpec) -> Any:
    """Instancia la GruNet del §7.1 (torch lazy — CI corre sin el extra nn)."""
    from torch import nn

    class GruNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.gru = nn.GRU(len(spec.channels), spec.hidden, spec.layers, batch_first=True)
            self.drop = nn.Dropout(spec.dropout)
            self.head = nn.Linear(spec.hidden, 1)

        def forward(self, x: Any) -> Any:
            out, _ = self.gru(x)
            return self.head(self.drop(out[:, -1])).squeeze(-1)

    return GruNet()


def _train(x_tr: np.ndarray, y_tr: np.ndarray, spec: NnSpec) -> Any:
    """Entrena UNA vez (épocas fijas, determinista por seed) y devuelve la red."""
    import torch

    torch.manual_seed(spec.seed)
    net = _build_net(spec)
    opt = torch.optim.Adam(net.parameters(), lr=spec.lr)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    xt = torch.from_numpy(x_tr)
    yt = torch.from_numpy(y_tr.astype(np.float32))
    gen = torch.Generator().manual_seed(spec.seed)
    net.train()
    for _ in range(spec.epochs):
        perm = torch.randperm(len(xt), generator=gen)
        for i in range(0, len(xt), spec.batch_size):
            idx = perm[i : i + spec.batch_size]
            opt.zero_grad()
            loss = loss_fn(net(xt[idx]), yt[idx])
            loss.backward()
            opt.step()
    return net


def _predict(net: Any, x: np.ndarray) -> np.ndarray:
    import torch

    net.eval()
    with torch.no_grad():
        chunks = [
            torch.sigmoid(net(torch.from_numpy(x[i : i + 4096]))).numpy()
            for i in range(0, len(x), 4096)
        ]
    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)


def _fit_predict_nn(
    x_tr: np.ndarray, y_tr: np.ndarray, x_vas: list[np.ndarray], spec: NnSpec
) -> list[np.ndarray]:
    net = _train(x_tr, y_tr, spec)
    return [_predict(net, x_va) for x_va in x_vas]


# ── artefacto congelado (shadow §12.1): state_dict como tensores planos JSON ──
def artifact_from_net(net: Any, spec: NnSpec, extra: dict[str, Any]) -> dict[str, Any]:
    """Red → artefacto auditable sin pickle (mismo principio que el campeón)."""
    art: dict[str, Any] = {
        "kind": "gru_seq",
        "spec": asdict(spec),
        "state": {k: v.tolist() for k, v in net.state_dict().items()},
        **extra,
    }
    art["sha256"] = hashlib.sha256(json.dumps(art, sort_keys=True).encode()).hexdigest()
    return art


def predict_artifact(artifact: dict[str, Any], x: np.ndarray) -> np.ndarray:
    """Puntúa con la red congelada reconstruida del JSON (paridad exacta)."""
    import torch

    spec = NnSpec(**artifact["spec"])
    net = _build_net(spec)
    net.load_state_dict({k: torch.tensor(v) for k, v in artifact["state"].items()})
    return _predict(net, x)


def freeze(spec_uri: str, model_id: str) -> int:
    """Congela la receta §7.1 re-entrenada sobre TODA la iteración (la
    confirmación jamás entrena) → models/<model_id>.json para el shadow."""
    bucket = os.environ["HERMES_RESEARCH_BUCKET"]
    path = spec_uri.removeprefix(f"gs://{bucket}/")
    spec = NnSpec(**json.loads(gcs.bucket().blob(path).download_as_text()))
    panel = extremes_label(load_panel(spec.horizon_days), k=5)
    x_all, meta = build_sequences(panel, spec)
    iteration, confirmation = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(iteration) & meta["y"].notna()).to_numpy()
    x_tr, meta_tr = x_all[keep], meta[keep]
    net = _train(x_tr, meta_tr["y"].to_numpy(), spec)
    art = artifact_from_net(
        net,
        spec,
        {
            "model_id": model_id,
            "train_rows": int(len(meta_tr)),
            "train_from": str(meta_tr["ts"].min().date()),
            "train_to": str(meta_tr["ts"].max().date()),
            "confirmation_cut": str(pd.Timestamp(confirmation.min()).date()),
            "frozen_at": datetime.now(UTC).isoformat(),
        },
    )
    gcs.upload_json(art, f"models/{model_id}.json")
    print(
        f"[freeze-nn] {model_id}: {art['train_rows']:,} filas "
        f"({art['train_from']} → {art['train_to']}) · sha {art['sha256'][:12]}"
    )
    return 0


def run_nn_trial(spec: NnSpec) -> dict[str, Any]:
    panel = load_panel(spec.horizon_days)
    if spec.label != "extremes_k5":
        raise ValueError(f"label no soportado en fase NN: {spec.label}")
    panel = extremes_label(panel, k=5)
    x_all, meta = build_sequences(panel, spec)

    # particiones sobre el dominio de fechas del PANEL (mismo corte de confirmación
    # que los trials tabulares — comparabilidad y slice intocable idénticos)
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = meta["ts"].isin(iteration) & meta["fwd_ret_24h_mxn"].notna()
    x_all, meta = x_all[keep.to_numpy()], meta[keep].reset_index(drop=True)
    labeled_mask = meta["y"].notna().to_numpy()

    splits = hybrid_splits(iteration, seed=spec.seed, horizon_days=spec.horizon_days)
    block_acc: list[float] = []
    block_auc: list[float] = []
    per_split: dict[str, dict[str, Any]] = {}
    sig_all: pd.DataFrame | None = None
    result: dict[str, Any] = {
        **asdict(spec),
        "n_rows": int(len(meta)),
        "n_labeled": int(labeled_mask.sum()),
    }

    for split in splits:
        tr_mask = labeled_mask & meta["ts"].isin(split.train_dates).to_numpy()
        va_mask = labeled_mask & meta["ts"].isin(split.val_dates).to_numpy()
        if tr_mask.sum() < 500 or va_mask.sum() < 100:
            per_split[split.name] = {"error": "muestras insuficientes"}
            continue
        y_tr = meta.loc[tr_mask, "y"].to_numpy()
        if split.name == "temporal_holdout":
            all_mask = meta["ts"].isin(split.val_dates).to_numpy()
            p_va, p_all = _fit_predict_nn(
                x_all[tr_mask], y_tr, [x_all[va_mask], x_all[all_mask]], spec
            )
            sig_all = meta[all_mask][
                ["ts", "symbol", "rv_20d", "fwd_ret_24h_mxn", "operable"]
            ].assign(p=p_all)
            result["precision_at_5"] = _precision_at_k(
                sig_all[["ts", "symbol", "fwd_ret_24h_mxn"]].assign(p=p_all)
            )
        else:
            (p_va,) = _fit_predict_nn(x_all[tr_mask], y_tr, [x_all[va_mask]], spec)
        m = _split_metrics(meta.loc[va_mask, "y"], p_va, spec.threshold)
        per_split[split.name] = m
        if split.name.startswith("block_draw"):
            block_acc.append(m["accuracy"])
            block_auc.append(m["auc_roc"])

    result |= {
        "acc_blocks_mean": round(float(np.mean(block_acc)), 4) if block_acc else None,
        "acc_blocks_std": round(float(np.std(block_acc)), 4) if block_acc else None,
        "acc_temporal": per_split.get("temporal_holdout", {}).get("accuracy"),
        "auc_blocks_mean": round(float(np.mean(block_auc)), 4) if block_auc else None,
        "auc_temporal": per_split.get("temporal_holdout", {}).get("auc_roc"),
        "per_split": per_split,
    }

    # phase check COMPLETO dentro del trial (el modelo ya está puntuado): la
    # evaluación económica primaria a H>14 es la media entre fases (§10)
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
    parser = argparse.ArgumentParser(description="Fase NN H12 — trial de secuencias")
    parser.add_argument("--spec", required=True, help="URI GCS del spec JSON")
    parser.add_argument("--freeze", action="store_true", help="congela para el shadow §12.1")
    parser.add_argument("--model-id", default="h12-gru-h28", help="id del artefacto congelado")
    args = parser.parse_args()
    if args.freeze:
        return freeze(args.spec, args.model_id)
    bucket = os.environ["HERMES_RESEARCH_BUCKET"]
    path = args.spec.removeprefix(f"gs://{bucket}/")
    spec = NnSpec(**json.loads(gcs.bucket().blob(path).download_as_text()))
    print(f"[nn] trial={spec.trial_id} model={spec.model} window={spec.window}")
    result = run_nn_trial(spec)
    result["ran_at"] = datetime.now(UTC).isoformat()
    gcs.upload_json(result, f"experiments/trials/{spec.trial_id}.json")
    pc = result.get("phase_check", {})
    print(
        f"[nn] {spec.trial_id}: acc_bloques={result.get('acc_blocks_mean')} · "
        f"AUC bloques={result.get('auc_blocks_mean')} temporal={result.get('auc_temporal')} · "
        f"exceso fase-media={pc.get('excess_mean')} ({pc.get('fases_positivas')}/"
        f"{pc.get('n_fases')} fases) · PF fase-media={pc.get('pf_phase_mean')} · "
        f"sin-top1={pc.get('exc_sin_top1_mean')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
