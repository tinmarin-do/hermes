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

Multi-stream (§12.1): el mismo protocolo corre para el campeón Y sus challengers
congelados (hoy: GRU NN-1) — mismas fechas de grilla, mismo universo, ledgers y
reportes separados. La comparación cara a cara forward es el único juez legítimo
entre dos candidatos que fallan M4-bloques.

Modos:  --freeze (campeón) | --emit [--model ID] | --emit-all | --eval [--model ID]
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

CHAMPION_ID = "h12-ext5-h28"
GRU_ID = "h12-gru-h28"
# streams del shadow (§12/§12.1): id → tipo de scorer. Mismo protocolo para todos:
# artefacto congelado auditable, grilla 28d propia, ledger y reporte separados.
STREAMS: dict[str, str] = {CHAMPION_ID: "logistic", GRU_ID: "gru_seq"}
CADENCE_DAYS = 28
SPEC_BLOB = "experiments/specs/manual/h12-h28.json"  # receta del campeón (--freeze)
MATURITY_TOLERANCE_DAYS = 3  # entrada madura si existe emisión en [D+28, D+28+tol]


def model_blob(sid: str) -> str:
    return f"models/{sid}.json"


def config_blob(sid: str) -> str:
    return f"shadow/{sid}/config.json"


def days_prefix(sid: str) -> str:
    return f"shadow/{sid}/days/"


def report_stem(sid: str) -> str:
    return f"reports/shadow_{sid.replace('-', '_')}"


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
    model_id: str = CHAMPION_ID,
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
    out: dict[str, Any] = {"model_id": model_id, "n_entries": len(entries)}
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
        "model_id": CHAMPION_ID,
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
    gcs.upload_json(artifact, model_blob(CHAMPION_ID))
    coefs = dict(zip(spec.features, artifact["coef"], strict=True))
    print(
        f"[freeze] {CHAMPION_ID}: {artifact['train_rows']:,} filas "
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


# ── emit: delta Bitso → features/secuencias → p → ledger del día por stream ───
def _bitso_panel() -> pd.DataFrame:
    """Panel diario Bitso operable (barras completas ya filtradas por el caller)
    con las columnas dummy que esperan compute_matrix/build_sequences."""
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
    panel["source"], panel["operable"] = "bitso", True
    panel["y"], panel["fwd_ret_24h_mxn"] = np.nan, np.nan
    return panel


def _day_logistic(model: dict[str, Any], panel: pd.DataFrame) -> tuple[Any, pd.DataFrame, list[str]]:
    """Matriz del catálogo causal de features.py — paridad con el training."""
    from src.lab.features import build_candidates, compute_matrix

    needed = [*model["features"], "rv_20d"]
    cands = [c for c in build_candidates() if c.name in set(needed)]
    matrix = compute_matrix(panel, cands)
    matrix["close"] = panel["close"].values
    decision = pd.Timestamp(matrix["ts"].max())
    day = matrix[matrix["ts"] == decision].dropna(subset=needed).set_index("symbol")
    if not day.empty:
        day = day.assign(p=score_probability(model, day))
    return decision, day, needed


def _day_gru(model: dict[str, Any], panel: pd.DataFrame) -> tuple[Any, pd.DataFrame, list[str]]:
    """Secuencias del §7.1 sobre el panel Bitso + forward de la red congelada."""
    from src.lab.nn_trial import NnSpec, build_sequences, predict_artifact

    spec = NnSpec(**model["spec"])
    x, meta = build_sequences(panel, spec)
    decision = pd.Timestamp(meta["ts"].max())
    mask = (meta["ts"] == decision).to_numpy()
    day = meta[mask].copy()
    day["p"] = predict_artifact(model, x[mask])
    closes = panel[panel["ts"] == decision].set_index("symbol")["close"]
    day["close"] = day["symbol"].map(closes)
    day = day.dropna(subset=["rv_20d", "close"]).set_index("symbol")
    return decision, day, ["rv_20d"]


def _emit_one(sid: str, panel: pd.DataFrame) -> int:
    model = json.loads(gcs.bucket().blob(model_blob(sid)).download_as_text())
    scorer = _day_logistic if STREAMS[sid] == "logistic" else _day_gru
    decision, day, extras = scorer(model, panel)
    if day.empty:
        print(f"[emit:{sid}] sin filas válidas para {decision.date()} — nada que emitir")
        return 1

    cfg_ref = gcs.bucket().blob(config_blob(sid))
    cfg = json.loads(cfg_ref.download_as_text()) if cfg_ref.exists() else None
    if cfg is None:
        cfg = {
            "model_id": sid,
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

    spec = model["spec"]
    if due:
        params = StrategyParams(threshold=spec["threshold"], top_k=spec["top_k"])
        weights = {s: round(float(w), 6) for s, w in _weights_for_day(day, params).items()}
        cfg["last_rebalance"], cfg["holdings"] = str(decision.date()), weights
    else:
        weights = cfg["holdings"]

    entry = {
        "model_id": sid,
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
                **{f: round(float(r[f]), 6) for f in extras},
            }
            for s, r in day.iterrows()
        ],
        "weights": weights,
        "prices_mxn": {s: float(r["close"]) for s, r in day.iterrows()},
    }
    gcs.upload_json(entry, f"{days_prefix(sid)}{decision.date()}.json")
    gcs.upload_json(cfg, config_blob(sid))
    tag = "REBALANCE" + (" catch-up" if catch_up else "") if is_rebalance else "hold"
    print(
        f"[emit:{sid}] {decision.date()} periodo {period} [{tag}] · universo {len(day)} · "
        f"pesos {weights or 'CASH'}"
    )
    return 0


def emit(streams: list[str]) -> int:
    from src.lab.bitso_data import delta

    delta()
    panel = complete_days(_bitso_panel(), datetime.now(UTC))
    rc = 0
    for sid in streams:
        rc = _emit_one(sid, panel) or rc
        rc = evaluate_and_report(sid) or rc
    return rc


# ── eval: track record + AUC forward → reports/ ────────────────────────────────
def evaluate_and_report(sid: str = CHAMPION_ID) -> int:
    entries = [
        json.loads(gcs.bucket().blob(name).download_as_text())
        for name in sorted(gcs.list_blobs(days_prefix(sid)))
    ]
    result = evaluate(entries, model_id=sid)
    result["generated"] = datetime.now(UTC).isoformat()
    gcs.upload_json(result, f"{report_stem(sid)}.json")

    lines = [
        f"# Shadow pre-firewall — {sid} (cadencia {CADENCE_DAYS}d) · PAPEL, cero riesgo",
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
    gcs.upload_text("\n".join(lines), f"{report_stem(sid)}.md")
    print(
        f"[eval:{sid}] {result.get('n_entries', 0)} emisiones · exceso total "
        f"{result.get('excess_total_pct', '—')} · AUC grilla {result.get('auc_grid', '—')} "
        f"(n={result.get('auc_grid_n', 0)})"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Shadow pre-firewall H12 (multi-stream)")
    p.add_argument("--freeze", action="store_true", help="congela al campeón logístico")
    p.add_argument("--emit", action="store_true", help="emite UN stream (--model)")
    p.add_argument("--emit-all", action="store_true", help="emite todos los streams")
    p.add_argument("--eval", action="store_true")
    p.add_argument("--model", default=CHAMPION_ID, choices=sorted(STREAMS))
    a = p.parse_args()
    if a.freeze:
        return freeze()
    if a.emit_all:
        return emit(sorted(STREAMS))
    if a.emit:
        return emit([a.model])
    if a.eval:
        return evaluate_and_report(a.model)
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
