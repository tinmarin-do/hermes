"""Shadow pre-firewall del campeón H12 `ext5-h28` (DESIGN_H12 §12) — papel, cero riesgo.

Corre el modelo CONGELADO (logistic sobre ret_63d, label extremes_k5, H=28) hacia
adelante en el venue real y acumula la única evidencia que puede zanjar M4 sin
verdict-shopping: datos del futuro. No consume el slice de confirmación (one-shot
reservado) y NO toca el pipeline live.

Decisiones de diseño (pre-registradas en §12 ANTES de la primera emisión):
- **Ledger en el bucket de research** (`shadow/h12-ext5-h28/days/<fecha>.json`), NO en
  el DuckDB del brain: el estado live sincroniza por download→modify→upload
  (state_sync) y un segundo escritor haría race. Esquema espejo de `shadow_signals`
  (symbol, p, weights) — importable después si se promueve.
- **Universo = libros MXN operables de Bitso** (~10 símbolos; NON_TARGET fuera): la
  caja registradora del arco. Con n=10 y k=5, extremes_k5 degenera a beats-median
  (banda media vacía) — el label realizado del AUC forward ES ese label degenerado.
- **Features desde closes Bitso MXN** (autonomía: Binance geo-bloquea GCP). El modelo
  es monótono en ret_63d y el FX es factor común del día → el ranking top-5 es
  idéntico al de USDT; el nivel de p se desplaza ~nada (auditable: se registra
  ret_63d crudo por símbolo en cada emisión).
- **Cadencia = 28d (REGLA EN PIEDRA §3)**: emisión DIARIA de probabilidades (evidencia
  AUC), rebalanceo SOLO en la grilla ancla+k·28. Día de grilla perdido → catch-up en
  la siguiente emisión, la grilla NO se re-ancla.
- **Freeze**: receta del spec re-entrenada sobre TODA la iteración (Binance, el slice
  de confirmación jamás entrena). Artefacto JSON auditable (scaler+coefs+sha), sin
  pickle.

Modos:  --freeze | --emit (delta Bitso → señal → ledger → eval) | --eval
"""

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.backtest_daily import FEE_RATE, SLIPPAGE, StrategyParams, _weights_for_day
from src.lab.dataset import NON_TARGET, _daily_bars

MODEL_ID = "h12-ext5-h28"
CADENCE_DAYS = 28
SPEC_BLOB = "experiments/specs/manual/h12-h28.json"
MODEL_BLOB = f"models/{MODEL_ID}.json"
CONFIG_BLOB = f"shadow/{MODEL_ID}/config.json"
DAYS_PREFIX = f"shadow/{MODEL_ID}/days/"
REPORT_STEM = f"reports/shadow_{MODEL_ID.replace('-', '_')}"
MATURITY_TOLERANCE_DAYS = 3  # entrada madura si existe emisión en [D+28, D+28+tol]


# ── funciones puras (testeables sin GCS) ───────────────────────────────────────
def score_probability(model: dict[str, Any], x: pd.DataFrame) -> np.ndarray:
    """sigmoid(coef·(x−μ)/σ + b) — réplica exacta de scaler+logística del freeze."""
    z = (x[model["features"]].to_numpy(dtype=float) - np.asarray(model["scaler_mean"])) / (
        np.asarray(model["scaler_scale"])
    )
    logit = z @ np.asarray(model["coef"]) + float(model["intercept"])
    return np.asarray(1.0 / (1.0 + np.exp(-logit)))


def rebalance_due(
    anchor: pd.Timestamp, last_rebalance: pd.Timestamp | None, decision: pd.Timestamp
) -> tuple[bool, bool, int]:
    """(due, catch_up, period_index). Grilla ancla+k·28 fija; día perdido → catch-up
    en la siguiente emisión SIN re-anclar (period_index sigue contando desde ancla)."""
    period = (decision - anchor).days // CADENCE_DAYS
    if last_rebalance is None:
        return True, False, period
    last_period = (last_rebalance - anchor).days // CADENCE_DAYS
    due = period > last_period
    catch_up = due and (decision - anchor).days % CADENCE_DAYS != 0
    return due, catch_up, period


def realized_labels(fwd_ret: dict[str, float]) -> dict[str, int]:
    """Label realizado del universo shadow: top-mitad=1 / bottom-mitad=0 por rank
    de retorno forward (con n=10 y k=5, extremes_k5 == beats-median; empates
    method='first' como en el training)."""
    s = pd.Series(fwd_ret)
    rank = s.rank(method="first", ascending=False)
    return {sym: int(rank[sym] <= len(s) / 2) for sym in s.index}


def evaluate(
    entries: list[dict[str, Any]],
    fee_rate: float = FEE_RATE,
    slippage: float = SLIPPAGE,
) -> dict[str, Any]:
    """Track record + AUC forward desde el ledger (puro: solo lee las emisiones).

    Cartera: pesos objetivo en rebalanceos, drift buy&hold entre ellos, fees sobre
    turnover contra los pesos DRIFTEADOS (más realista que el backtest, que usa el
    target previo). Benchmark: EW buy&hold del universo del primer rebalanceo, fee
    de entrada única. AUC: p emitida vs label realizado a 28d — grilla (primaria,
    apuestas independientes) y diaria solapada (secundaria, obs correlacionadas).
    """
    entries = sorted(entries, key=lambda e: e["decision_date"])
    cost = fee_rate + slippage
    out: dict[str, Any] = {"model_id": MODEL_ID, "n_entries": len(entries)}
    if not entries:
        return out | {"error": "ledger vacío"}

    dates = [pd.Timestamp(e["decision_date"]) for e in entries]
    out["first_date"], out["last_date"] = str(dates[0].date()), str(dates[-1].date())
    out["n_rebalances"] = sum(1 for e in entries if e.get("is_rebalance"))

    # ── track record ──
    prices: dict[str, float] = {}  # memoria del último close conocido por símbolo
    v, cash = 1.0, 1.0
    shares: dict[str, float] = {}
    bench_shares: dict[str, float] | None = None
    track: list[dict[str, Any]] = []
    rebalance_marks: list[tuple[pd.Timestamp, float, float]] = []
    for e, d in zip(entries, dates, strict=True):
        prices.update(e.get("prices_mxn", {}))
        if bench_shares is None:
            if not e.get("is_rebalance"):
                continue  # el track arranca en el primer rebalanceo
            uni = sorted(e["prices_mxn"])
            bench_shares = {s: (1.0 - cost) / len(uni) / prices[s] for s in uni}
        v = cash + sum(sh * prices[s] for s, sh in shares.items())
        if e.get("is_rebalance"):
            w_target: dict[str, float] = e.get("weights", {})
            w_drift = {s: sh * prices[s] / v for s, sh in shares.items()}
            turnover = sum(
                abs(w_target.get(s, 0.0) - w_drift.get(s, 0.0))
                for s in set(w_target) | set(w_drift)
            )
            v *= 1.0 - cost * turnover
            shares = {s: w * v / prices[s] for s, w in w_target.items()}
            cash = v * (1.0 - sum(w_target.values()))
            rebalance_marks.append((d, v, _bench_value(bench_shares, prices)))
        b = _bench_value(bench_shares, prices)
        track.append({"date": str(d.date()), "v": round(v, 6), "bench": round(b, 6)})

    out["track"] = track
    if track:
        out["total_return_pct"] = round((track[-1]["v"] - 1) * 100, 3)
        out["bench_return_pct"] = round((track[-1]["bench"] - 1) * 100, 3)
        out["excess_total_pct"] = round(out["total_return_pct"] - out["bench_return_pct"], 3)
    periods = []
    marks = rebalance_marks + ([(dates[-1], track[-1]["v"], track[-1]["bench"])] if track else [])
    for (d0, v0, b0), (d1, v1, b1) in zip(marks, marks[1:], strict=False):
        if d1 == d0:
            continue
        rp, rb = v1 / v0 - 1, b1 / b0 - 1
        periods.append(
            {
                "from": str(d0.date()),
                "to": str(d1.date()),
                "net_pct": round(rp * 100, 3),
                "bench_pct": round(rb * 100, 3),
                "excess_pct": round((rp - rb) * 100, 3),
            }
        )
    out["periods"] = periods

    # ── AUC forward (madurez 28d) ──
    by_date = dict(zip(dates, entries, strict=True))
    grid_scores: list[tuple[float, int]] = []
    daily_scores: list[tuple[float, int]] = []
    for d, e in by_date.items():
        target = d + pd.Timedelta(days=CADENCE_DAYS)
        mature = next(
            (
                by_date[d2]
                for d2 in sorted(by_date)
                if target <= d2 <= target + pd.Timedelta(days=MATURITY_TOLERANCE_DAYS)
            ),
            None,
        )
        if mature is None:
            continue
        p0, p1 = e.get("prices_mxn", {}), mature.get("prices_mxn", {})
        fwd = {s: p1[s] / p0[s] - 1 for s in p0 if s in p1}
        labels = realized_labels(fwd)
        probs = {u["symbol"]: u["p"] for u in e.get("universe", [])}
        pairs = [(probs[s], labels[s]) for s in labels if s in probs]
        daily_scores.extend(pairs)
        if e.get("is_rebalance"):
            grid_scores.extend(pairs)
    for name, scored in (("auc_grid", grid_scores), ("auc_daily_overlap", daily_scores)):
        ys = [y for _, y in scored]
        if len(set(ys)) == 2:
            from sklearn.metrics import roc_auc_score

            out[name] = round(float(roc_auc_score(ys, [p for p, _ in scored])), 4)
        out[f"{name}_n"] = len(scored)
    return out


def _bench_value(bench_shares: dict[str, float] | None, prices: dict[str, float]) -> float:
    if not bench_shares:
        return 1.0
    return sum(sh * prices[s] for s, sh in bench_shares.items())


# ── freeze: receta del spec sobre TODA la iteración (confirmación jamás entrena) ──
def freeze() -> int:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    from src.lab.dataset import extremes_label
    from src.lab.features import build_candidates, compute_matrix
    from src.lab.splits import partitions
    from src.lab.train import TrialSpec, load_panel

    spec = TrialSpec(**json.loads(gcs.bucket().blob(SPEC_BLOB).download_as_text()))
    assert spec.label == "extremes_k5" and spec.model == "logistic"
    panel = extremes_label(load_panel(spec.horizon_days), k=5)
    matrix = compute_matrix(panel, build_candidates())
    iteration, confirmation = partitions(pd.DatetimeIndex(matrix["ts"].unique()))
    labeled = (
        matrix[matrix["ts"].isin(iteration)]
        .dropna(subset=[*spec.features, "y"])
        .sort_values(["symbol", "ts"])
    )
    x, y = labeled[spec.features], labeled["y"]
    scaler = StandardScaler().fit(x)
    clf = LogisticRegression(
        max_iter=1000,
        C=float(spec.params.get("C", 1.0)),
        class_weight=spec.params.get("class_weight"),
        random_state=spec.seed,
    ).fit(scaler.transform(x), y)

    artifact: dict[str, Any] = {
        "model_id": MODEL_ID,
        "spec": asdict(spec),
        "features": list(spec.features),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "coef": clf.coef_[0].tolist(),
        "intercept": float(clf.intercept_[0]),
        "train_rows": int(len(labeled)),
        "train_from": str(labeled["ts"].min().date()),
        "train_to": str(labeled["ts"].max().date()),
        "confirmation_cut": str(pd.Timestamp(confirmation.min()).date()),
        "frozen_at": datetime.now(UTC).isoformat(),
    }
    artifact["sha256"] = hashlib.sha256(json.dumps(artifact, sort_keys=True).encode()).hexdigest()
    gcs.upload_json(artifact, MODEL_BLOB)
    coefs = dict(zip(spec.features, artifact["coef"], strict=True))
    print(
        f"[freeze] {MODEL_ID}: {artifact['train_rows']:,} filas "
        f"({artifact['train_from']} → {artifact['train_to']}) · coef {coefs} · "
        f"b {artifact['intercept']:.4f} · sha {artifact['sha256'][:12]}"
    )
    return 0


def complete_days(matrix: pd.DataFrame, now_utc: datetime) -> pd.DataFrame:
    """Solo barras de días COMPLETOS: la barra de hoy cierra a las 00:00 de mañana.

    El umbral de ≥20 velas de _daily_bars deja pasar el día en curso si el job
    corre tarde (visto en la emisión inaugural, corrida a las ~19h UTC con 20
    velas) — el filtro por fecha lo excluye siempre, a cualquier hora."""
    return matrix[matrix["ts"] < pd.Timestamp(now_utc.date())]


# ── emit: delta Bitso → features → p → ledger del día ─────────────────────────
def _bitso_matrix(needed: list[str]) -> pd.DataFrame:
    """Panel diario Bitso operable → matriz con las features del modelo (cómputo
    del MISMO catálogo causal de features.py — paridad con el training)."""
    from src.lab.features import build_candidates, compute_matrix

    frames = []
    for blob in sorted(gcs.list_blobs("bronze/bitso_ohlcv_1h/")):
        book = blob.split("/")[-1].removesuffix(".parquet").replace("_", "/")
        base = book.split("/")[0]
        if base in NON_TARGET:
            continue
        bars = _daily_bars(gcs.read_parquet(blob)).reset_index().rename(columns={"index": "ts"})
        bars["symbol"] = base
        frames.append(bars)
    panel = pd.concat(frames, ignore_index=True).sort_values(["symbol", "ts"])
    panel["source"], panel["y"], panel["fwd_ret_24h_mxn"] = "bitso", np.nan, np.nan
    cands = [c for c in build_candidates() if c.name in set(needed)]
    matrix = compute_matrix(panel, cands)
    matrix["close"] = panel["close"].values
    return matrix


def emit() -> int:
    from src.lab.bitso_data import delta

    delta()
    model = json.loads(gcs.bucket().blob(MODEL_BLOB).download_as_text())
    spec = model["spec"]
    needed = [*model["features"], "rv_20d"]
    matrix = complete_days(_bitso_matrix(needed), datetime.now(UTC))

    decision = pd.Timestamp(matrix["ts"].max())
    day = matrix[matrix["ts"] == decision].dropna(subset=needed).set_index("symbol")
    if day.empty:
        print(f"[emit] sin filas válidas para {decision.date()} — nada que emitir")
        return 1
    day = day.assign(p=score_probability(model, day))

    cfg_blob = gcs.bucket().blob(CONFIG_BLOB)
    cfg = json.loads(cfg_blob.download_as_text()) if cfg_blob.exists() else None
    if cfg is None:
        cfg = {
            "model_id": MODEL_ID,
            "model_sha256": model["sha256"],
            "anchor": str(decision.date()),
            "cadence_days": CADENCE_DAYS,
            "created_at": datetime.now(UTC).isoformat(),
            "last_rebalance": None,
            "holdings": {},
        }
    anchor = pd.Timestamp(cfg["anchor"])
    last_rb = pd.Timestamp(cfg["last_rebalance"]) if cfg["last_rebalance"] else None
    due, catch_up, period = rebalance_due(anchor, last_rb, decision)
    is_rebalance = due or (last_rb is not None and last_rb == decision)  # re-emisión idempotente

    if due:
        params = StrategyParams(threshold=spec["threshold"], top_k=spec["top_k"])
        weights = {s: round(float(w), 6) for s, w in _weights_for_day(day, params).items()}
        cfg["last_rebalance"], cfg["holdings"] = str(decision.date()), weights
    else:
        weights = cfg["holdings"]

    entry = {
        "model_id": MODEL_ID,
        "model_sha256": model["sha256"],
        "decision_date": str(decision.date()),
        "emitted_at": datetime.now(UTC).isoformat(),
        "period_index": period,
        "is_rebalance": is_rebalance,
        "catch_up": catch_up,
        "universe": [
            {
                "symbol": s,
                "p": round(float(r["p"]), 6),
                "close_mxn": float(r["close"]),
                **{f: round(float(r[f]), 6) for f in needed},
            }
            for s, r in day.iterrows()
        ],
        "weights": weights,
        "prices_mxn": {s: float(r["close"]) for s, r in day.iterrows()},
    }
    gcs.upload_json(entry, f"{DAYS_PREFIX}{decision.date()}.json")
    gcs.upload_json(cfg, CONFIG_BLOB)
    tag = "REBALANCE" + (" catch-up" if catch_up else "") if is_rebalance else "hold"
    print(
        f"[emit] {decision.date()} periodo {period} [{tag}] · universo {len(day)} · "
        f"pesos {weights or 'CASH'}"
    )
    return 0


# ── eval: track record + AUC forward → reports/ ────────────────────────────────
def evaluate_and_report() -> int:
    entries = [
        json.loads(gcs.bucket().blob(name).download_as_text())
        for name in sorted(gcs.list_blobs(DAYS_PREFIX))
    ]
    result = evaluate(entries)
    result["generated"] = datetime.now(UTC).isoformat()
    gcs.upload_json(result, f"{REPORT_STEM}.json")

    lines = [
        f"# Shadow pre-firewall — {MODEL_ID} (cadencia {CADENCE_DAYS}d) · PAPEL, cero riesgo",
        f"\nGenerado: {result['generated']} · emisiones {result.get('n_entries', 0)} "
        f"({result.get('first_date', '—')} → {result.get('last_date', '—')}) · "
        f"rebalanceos {result.get('n_rebalances', 0)}\n",
    ]
    if result.get("track"):
        lines += [
            f"Equity: **{result['total_return_pct']:+.2f}%** vs bench EW "
            f"{result['bench_return_pct']:+.2f}% → exceso **{result['excess_total_pct']:+.2f}%**\n",
            "| periodo | neto | bench | exceso |",
            "|---|---|---|---|",
            *(
                f"| {p['from']} → {p['to']} | {p['net_pct']:+.2f}% | {p['bench_pct']:+.2f}% "
                f"| {p['excess_pct']:+.2f}% |"
                for p in result["periods"]
            ),
            "",
        ]
    lines.append(
        f"AUC forward — grilla (primaria): {result.get('auc_grid', '—')} "
        f"(n={result.get('auc_grid_n', 0)}) · diaria solapada (secundaria): "
        f"{result.get('auc_daily_overlap', '—')} (n={result.get('auc_daily_overlap_n', 0)})"
    )
    gcs.upload_text("\n".join(lines), f"{REPORT_STEM}.md")
    print(
        f"[eval] {result.get('n_entries', 0)} emisiones · exceso total "
        f"{result.get('excess_total_pct', '—')} · AUC grilla {result.get('auc_grid', '—')} "
        f"(n={result.get('auc_grid_n', 0)})"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Shadow pre-firewall H12 ext5-h28")
    p.add_argument("--freeze", action="store_true")
    p.add_argument("--emit", action="store_true")
    p.add_argument("--eval", action="store_true")
    a = p.parse_args()
    if a.freeze:
        return freeze()
    if a.emit:
        rc = emit()
        return rc if rc else evaluate_and_report()
    if a.eval:
        return evaluate_and_report()
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
