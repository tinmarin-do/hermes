"""Estudio SENSE-FIRST de variables (Fase D1, arco H11) — genera el dossier del gate.

Por cada candidata del catálogo (features.py), sobre el sample de estudio:
  distribución/outliers · estabilidad por año · relación con el target (rate de
  y=1 por decil + IC Spearman) · lectura por régimen de vol · canary anti-leakage.
Redundancia: matriz de correlación entre candidatas (sección global).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.study"
Escribe reports/feature_dossier.md + .json  →  GATE: Erika aprueba el conjunto.
"""

import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.lab import gcs
from src.lab.features import Candidate, build_candidates, compute_matrix
from src.lab.splits import CONFIRMATION_FRACTION

# Sample de estudio: 2 majors + 2 mid + 1 chico (representativos, no exhaustivos)
STUDY_SYMBOLS = ["BTC", "ETH", "SOL", "DOGE", "SAND"]
CANARY_DATES = 40  # nº de fechas aleatorias para el test de truncado


def _iteration_only(panel: pd.DataFrame) -> pd.DataFrame:
    """Excluye el slice de confirmación (últ. 15%) — el estudio JAMÁS lo mira."""
    dates = pd.DatetimeIndex(pd.to_datetime(panel["ts"]).unique()).sort_values()
    cut = dates[int(len(dates) * (1 - CONFIRMATION_FRACTION))]
    return panel[pd.to_datetime(panel["ts"]) < cut].copy()


def _decile_table(feat: pd.Series, y: pd.Series) -> list[dict[str, Any]]:
    df = pd.DataFrame({"f": feat, "y": y}).dropna()
    if df["f"].nunique() < 10:  # categóricas (dow, quincena): rate por valor
        g = df.groupby("f")["y"].agg(["mean", "count"])
        return [
            {"bucket": str(k), "y_rate": round(v["mean"], 4), "n": int(v["count"])}
            for k, v in g.iterrows()
        ]
    df["decil"] = pd.qcut(df["f"], 10, labels=False, duplicates="drop")
    g = df.groupby("decil")["y"].agg(["mean", "count"])
    return [
        {"bucket": f"D{int(k) + 1}", "y_rate": round(v["mean"], 4), "n": int(v["count"])}
        for k, v in g.iterrows()
    ]


def _canary_leakage(panel: pd.DataFrame, cand: Candidate, rng: np.random.Generator) -> bool:
    """Feature en t con serie completa == con serie truncada en t (sin lookahead)."""
    full = cand.fn(panel)
    dates = pd.DatetimeIndex(pd.to_datetime(panel["ts"]).unique()).sort_values()
    # evitar el warmup: solo fechas con lookback completo
    usable = dates[max(cand.min_lookback_days + 5, 10) :]
    if len(usable) == 0:
        return True
    sample = rng.choice(len(usable), size=min(CANARY_DATES, len(usable)), replace=False)
    # Ventana local [t − 2·lookback − 40d, t]: detecta lookahead igual que truncar
    # toda la historia (los rolling solo miran `lookback` días) pero evita recomputar
    # features caras (Hurst) sobre años completos en cada una de las 40 fechas.
    for i in sample:
        t = usable[i]
        ts_col = pd.to_datetime(panel["ts"])
        lo = t - pd.Timedelta(days=2 * cand.min_lookback_days + 40)
        trunc = panel[(ts_col <= t) & (ts_col >= lo)]
        vals_full = full[ts_col == t]
        vals_trunc = cand.fn(trunc)[pd.to_datetime(trunc["ts"]) == t]
        a, b = vals_full.to_numpy(dtype=float), vals_trunc.to_numpy(dtype=float)
        if len(a) != len(b):
            return False
        both = ~(np.isnan(a) & np.isnan(b))
        # rtol 1e-4: un lookahead real (p.ej. shift mal puesto) difiere a nivel %;
        # el residuo de memoria EWMA fuera de la ventana local es ~1e-5 — pasa.
        if not np.allclose(a[both], b[both], rtol=1e-4, atol=1e-12, equal_nan=True):
            return False
    return True


def main() -> int:
    panel = gcs.read_parquet("datasets/daily_v1.parquet")
    panel = panel[(panel["source"] == "binance") & (panel["symbol"].isin(STUDY_SYMBOLS))]
    panel["ts"] = pd.to_datetime(panel["ts"])

    # FX como columna del panel (para el grupo 6)
    fx = gcs.read_parquet("fx/usdmxn.parquet")
    panel = panel.merge(fx.rename(columns={"date": "ts"}), on="ts", how="left")

    panel = _iteration_only(panel).sort_values(["symbol", "ts"]).reset_index(drop=True)
    print(f"[study] sample: {STUDY_SYMBOLS} · {len(panel):,} filas (solo iteración)")

    candidates = build_candidates()
    matrix = compute_matrix(panel, candidates)
    rng = np.random.default_rng(11)

    fichas = []
    for cand in candidates:
        feat, y = matrix[cand.name], matrix["y"]
        valid = feat.notna()
        ic, ic_p = (np.nan, np.nan)
        if valid.sum() > 100 and feat[valid].nunique() > 1:
            ic, ic_p = spearmanr(feat[valid], matrix.loc[valid, "fwd_ret_24h_mxn"])
        per_year = (
            pd.DataFrame({"f": feat, "yr": matrix.ts.dt.year})
            .dropna()
            .groupby("yr")["f"]
            .agg(["mean", "std"])
            .round(4)
            .to_dict("index")
        )
        # lectura condicionada a régimen de vol (terciles de rv_20d)
        rv = matrix.get("rv_20d")
        by_regime = {}
        if rv is not None and rv.notna().sum() > 300:
            tercil = pd.qcut(rv, 3, labels=["vol_baja", "vol_media", "vol_alta"])
            for t in ["vol_baja", "vol_media", "vol_alta"]:
                m = (tercil == t) & valid
                if m.sum() > 100 and feat[m].nunique() > 1:
                    r, _ = spearmanr(feat[m], matrix.loc[m, "fwd_ret_24h_mxn"])
                    by_regime[t] = round(float(r), 4)
        leak_ok = _canary_leakage(panel, cand, rng)
        fichas.append(
            {
                "name": cand.name,
                "group": cand.group,
                "rationale": cand.rationale,
                "min_lookback_days": cand.min_lookback_days,
                "coverage": round(float(valid.mean()), 4),
                "mean": round(float(feat.mean()), 6),
                "std": round(float(feat.std()), 6),
                "skew": round(float(feat.skew()), 3),
                "outliers_3sigma_pct": round(
                    float((np.abs((feat - feat.mean()) / feat.std()) > 3).mean()), 4
                ),
                "ic_spearman": None if np.isnan(ic) else round(float(ic), 4),
                "ic_pvalue": None if np.isnan(ic_p) else round(float(ic_p), 6),
                "ic_por_regimen_vol": by_regime,
                "y_rate_por_decil": _decile_table(feat, y),
                "estabilidad_por_año": per_year,
                "canary_leakage_ok": bool(leak_ok),
            }
        )
        print(
            f"  {cand.name:16s} IC={ic if not np.isnan(ic) else float('nan'):+.4f} "
            f"canary={'OK' if leak_ok else '🚨 FUGA'}"
        )

    # redundancia global
    feat_cols = [c.name for c in candidates]
    corr = matrix[feat_cols].corr().round(3)
    high_pairs = [
        {"a": a, "b": b, "corr": float(corr.loc[a, b])}
        for i, a in enumerate(feat_cols)
        for b in feat_cols[i + 1 :]
        if abs(corr.loc[a, b]) > 0.7
    ]

    gcs.upload_json(
        {
            "generated": datetime.now(UTC).isoformat(),
            "sample": STUDY_SYMBOLS,
            "rows": len(panel),
            "fichas": fichas,
            "redundancia_corr_gt_070": high_pairs,
        },
        "reports/feature_dossier.json",
    )
    gcs.upload_text(_render_md(fichas, high_pairs, len(panel)), "reports/feature_dossier.md")
    print("[study] → reports/feature_dossier.md (GATE: revisar con Erika)")
    return 0


def _render_md(fichas: list[dict[str, Any]], high_pairs: list[dict[str, Any]], n_rows: int) -> str:
    L = [
        "# Dossier de variables — Fase D1 arco H11 (SENSE FIRST)",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · sample {STUDY_SYMBOLS} · "
        f"{n_rows:,} filas (slice de confirmación EXCLUIDO)",
        "\n**GATE**: ninguna variable entra al entrenamiento sin visto bueno de Erika.",
        "Veredicto propuesto por ficha: ✅ entra · ⚠️ revisar · ❌ fuera.\n",
    ]
    for f in fichas:
        ic = f["ic_spearman"]
        strong = ic is not None and abs(ic) >= 0.02 and (f["ic_pvalue"] or 1) < 0.05
        verdict = (
            "❌ FUERA (fuga)"
            if not f["canary_leakage_ok"]
            else ("✅ entra" if strong else "⚠️ revisar (IC débil)")
        )
        L += [
            f"## `{f['name']}`  ({f['group']}) — {verdict}",
            f"\n**Racional:** {f['rationale']}",
            f"\n- lookback efectivo: {f['min_lookback_days']}d · cobertura: {f['coverage']:.0%}"
            f" · outliers>3σ: {f['outliers_3sigma_pct']:.1%}",
            f"- IC Spearman vs fwd_ret: **{ic}** (p={f['ic_pvalue']}) · por régimen vol: "
            f"{f['ic_por_regimen_vol'] or '—'}",
            f"- canary anti-leakage: {'OK' if f['canary_leakage_ok'] else '🚨 FUGA DETECTADA'}",
            "\n| decil | p(y=1) | n |",
            "|---|---|---|",
        ]
        for d in f["y_rate_por_decil"]:
            L.append(f"| {d['bucket']} | {d['y_rate']:.1%} | {d['n']:,} |")
        L.append("")
    L += ["## Redundancia (|corr| > 0.70)", ""]
    if high_pairs:
        L += ["| a | b | corr |", "|---|---|---|"]
        L += [f"| {p['a']} | {p['b']} | {p['corr']:+.3f} |" for p in high_pairs]
    else:
        L.append("Sin pares altamente redundantes.")
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
