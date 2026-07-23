"""mountains — catálogo de montañas multi-escala (H13 §5a, EDA descriptivo).

Idea de Erika (2026-07-13): la serie es "montañitas" auto-similares a toda escala.
Protocolo PRE-REGISTRADO en DESIGN_H13 §5a antes de mirar resultados:

- Segmentación ZigZag CAUSAL multi-tolerancia sobre cierres diarios: un extremo se
  confirma solo cuando el precio retrocede ≥ tol en su contra (el índice de
  confirmación se archiva — es la base del canary anti-hindsight y de la curva de
  identificabilidad del capítulo 2).
- Espécimen (montaña) = excursión valle→pico→valle confirmada.
- Taxonomía SIN escala: la identidad es la FORMA (camino normalizado a SHAPE_POINTS
  en [0,1]²); duración/altura reales se ARCHIVAN como atributos (transformación
  inversa + segunda pregunta: ¿chicos y grandes del mismo tipo se comportan igual?).
- Pregunta falsificable: ¿CONTINUO (fractal puro) o GRUMOS (arquetipos)? — silueta
  de k-means sobre formas reales vs GEMELOS SINTÉTICOS (block-bootstrap de retornos
  por símbolo: conserva distribución y clustering de vol, destruye el resto).

Descriptivo: NO cuenta al DSR. Cualquier regla que luego se evalúe económicamente
sí contará como trial.

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.mountains"
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs

TOLERANCES = (0.05, 0.10, 0.20, 0.35)  # §5a — grilla multi-escala pre-fijada
SHAPE_POINTS = 24
N_TWINS = 10
BLOCK_DAYS = 20
K_RANGE = range(2, 9)
SEED = 42


@dataclass(frozen=True)
class Pivot:
    idx: int  # posición del extremo
    kind: int  # +1 pico, -1 valle
    confirm_idx: int  # posición donde quedó CONFIRMADO (retroceso ≥ tol)


def zigzag_pivots(closes: np.ndarray, tol: float) -> list[Pivot]:
    """Pivotes confirmados de forma CAUSAL (sin mirar el futuro del confirm_idx).

    Un valle en i queda confirmado en j>i cuando close[j] ≥ close[i]·(1+tol);
    un pico simétrico con (1−tol). El último extremo en curso NUNCA se emite:
    una montaña solo existe cuando sus dos valles están confirmados.
    """
    if len(closes) < 3:
        return []
    pivots: list[Pivot] = []
    hi = lo = 0  # índices del máximo/mínimo corrientes
    direction = 0  # 0 = aún sin dirección; +1 buscando pico; -1 buscando valle
    for j in range(1, len(closes)):
        c = closes[j]
        if direction == 0:
            if c > closes[hi]:
                hi = j
            if c < closes[lo]:
                lo = j
            if c >= closes[lo] * (1 + tol):
                pivots.append(Pivot(lo, -1, j))
                direction, hi = +1, j
            elif c <= closes[hi] * (1 - tol):
                pivots.append(Pivot(hi, +1, j))
                direction, lo = -1, j
        elif direction == +1:  # buscando pico
            if c > closes[hi]:
                hi = j
            elif c <= closes[hi] * (1 - tol):
                pivots.append(Pivot(hi, +1, j))
                direction, lo = -1, j
        else:  # buscando valle
            if c < closes[lo]:
                lo = j
            elif c >= closes[lo] * (1 + tol):
                pivots.append(Pivot(lo, -1, j))
                direction, hi = +1, j
    return pivots


def shape_vector(path: np.ndarray, n: int = SHAPE_POINTS) -> np.ndarray:
    """Camino → forma sin escala: tiempo re-muestreado a n puntos, precio a [0,1]."""
    x_old = np.linspace(0.0, 1.0, len(path))
    y = np.interp(np.linspace(0.0, 1.0, n), x_old, path)
    lo, hi = float(y.min()), float(y.max())
    return (y - lo) / (hi - lo) if hi > lo else np.zeros(n)


def mountains_from_pivots(
    closes: np.ndarray, ts: pd.DatetimeIndex, pivots: list[Pivot], tol: float, symbol: str
) -> list[dict[str, Any]]:
    """Tripletas valle→pico→valle confirmadas → especímenes con forma + escala."""
    out: list[dict[str, Any]] = []
    for a, b, c in zip(pivots, pivots[1:], pivots[2:], strict=False):
        if not (a.kind == -1 and b.kind == +1 and c.kind == -1):
            continue
        v1, pk, v2 = a.idx, b.idx, c.idx
        path = closes[v1 : v2 + 1]
        dur = v2 - v1
        out.append(
            {
                "symbol": symbol,
                "tol": tol,
                "t_v1": str(ts[v1].date()),
                "t_peak": str(ts[pk].date()),
                "t_v2": str(ts[v2].date()),
                "confirm_idx_v2": c.confirm_idx,
                "dur_days": int(dur),
                "up_days": int(pk - v1),
                "down_days": int(v2 - pk),
                "height_pct": round(float(closes[pk] / closes[v1] - 1) * 100, 3),
                "drop_pct": round(float(1 - closes[v2] / closes[pk]) * 100, 3),
                "asym_time": round(float((pk - v1) / dur), 4) if dur else np.nan,
                "valley_ratio": round(float(closes[v2] / closes[v1]), 4),
                "shape": shape_vector(path).tolist(),
            }
        )
    return out


def catalog_series(closes: pd.Series, symbol: str) -> list[dict[str, Any]]:
    """Catálogo completo (todas las tolerancias) de UNA serie de cierres diarios."""
    ts = pd.DatetimeIndex(closes.index)
    arr = closes.to_numpy(dtype=float)
    out: list[dict[str, Any]] = []
    for tol in TOLERANCES:
        out.extend(mountains_from_pivots(arr, ts, zigzag_pivots(arr, tol), tol, symbol))
    return out


def synthetic_twin(closes: pd.Series, rng: np.random.Generator) -> pd.Series:
    """Gemelo block-bootstrap: bloques de BLOCK_DAYS log-retornos re-barajados.

    Conserva distribución de retornos y clustering de vol local (dentro del
    bloque); destruye cualquier estructura de mayor alcance. Lo que el gemelo
    reproduzca del catálogo real NO es estructura de mercado.
    """
    rets = np.diff(np.log(closes.to_numpy(dtype=float)))
    n_blocks = int(np.ceil(len(rets) / BLOCK_DAYS))
    starts = rng.integers(0, max(1, len(rets) - BLOCK_DAYS), size=n_blocks)
    shuffled = np.concatenate([rets[s : s + BLOCK_DAYS] for s in starts])[: len(rets)]
    prices = float(closes.iloc[0]) * np.exp(np.concatenate([[0.0], np.cumsum(shuffled)]))
    return pd.Series(prices, index=closes.index)


def silhouette_by_k(shapes: np.ndarray, seed: int = SEED) -> dict[int, float]:
    """Silueta media de k-means por k — la métrica del test continuo-vs-grumos."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    out: dict[int, float] = {}
    for k in K_RANGE:
        if len(shapes) <= k + 1:
            continue
        labels = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(shapes)
        out[k] = round(float(silhouette_score(shapes, labels)), 4)
    return out


def _summary(df: pd.DataFrame) -> dict[str, Any]:
    per_tol: dict[str, Any] = {}
    for tol, g in df.groupby("tol"):
        per_tol[str(tol)] = {
            "n": int(len(g)),
            "dur_days_q": [float(q) for q in g["dur_days"].quantile([0.25, 0.5, 0.75])],
            "height_pct_q": [float(q) for q in g["height_pct"].quantile([0.25, 0.5, 0.75])],
            "asym_time_median": round(float(g["asym_time"].median()), 4),
            "pct_valle_der_mas_bajo": round(float((g["valley_ratio"] < 1).mean()), 4),
        }
    return per_tol


def main() -> int:
    from src.lab.train import load_panel

    panel = load_panel(1)
    rng = np.random.default_rng(SEED)

    real: list[dict[str, Any]] = []
    twin_shapes: list[np.ndarray] = []
    twin_asym: list[float] = []
    twin_counts: list[int] = []
    for symbol, g in panel.groupby("symbol", observed=True):
        closes = g.set_index("ts")["close"].dropna()
        if len(closes) < 200:
            continue
        real.extend(catalog_series(closes, str(symbol)))
        for _ in range(N_TWINS):
            tw = catalog_series(synthetic_twin(closes, rng), f"{symbol}~twin")
            twin_counts.append(len(tw))
            twin_asym.extend(m["asym_time"] for m in tw)
            twin_shapes.extend(np.asarray(m["shape"]) for m in tw)

    df = pd.DataFrame(real)
    print(f"[mountains] especímenes reales: {len(df)} · gemelos: {sum(twin_counts)}")
    gcs.upload_parquet(df, "reports/mountains_catalog.parquet")

    shapes_real = np.stack(df["shape"].map(np.asarray))
    shapes_twin = np.stack(twin_shapes)
    sil_real = silhouette_by_k(shapes_real)
    # gemelos: silueta sobre un subsample del mismo tamaño que el real (comparable)
    idx = np.random.default_rng(SEED).choice(
        len(shapes_twin), size=min(len(shapes_real), len(shapes_twin)), replace=False
    )
    sil_twin = silhouette_by_k(shapes_twin[idx])

    verdict_margin = {
        k: round(sil_real[k] - sil_twin.get(k, np.nan), 4) for k in sil_real if k in sil_twin
    }
    grumos = any(m > 0.05 for m in verdict_margin.values() if not np.isnan(m))

    report = {
        "generated": datetime.now(UTC).isoformat(),
        "protocol": {
            "tolerances": TOLERANCES,
            "shape_points": SHAPE_POINTS,
            "n_twins": N_TWINS,
            "block_days": BLOCK_DAYS,
            "seed": SEED,
        },
        "n_real": int(len(df)),
        "n_twin": int(sum(twin_counts)),
        "per_tol": _summary(df),
        "asym_time_median_real": round(float(df["asym_time"].median()), 4),
        "asym_time_median_twin": round(float(np.median(twin_asym)), 4),
        "silhouette_real": sil_real,
        "silhouette_twin_samesize": sil_twin,
        "silhouette_margin": verdict_margin,
        "veredicto_preliminar": (
            "GRUMOS (silueta real supera al gemelo >0.05 en algún k)"
            if grumos
            else "CONTINUO (la silueta real no supera al gemelo — fractal puro domina)"
        ),
    }
    gcs.upload_json(report, "reports/mountains_h13.json")

    lines = [
        "# Catálogo de montañas H13 §5a — corrida 1\n",
        f"- Especímenes reales: **{len(df)}** · gemelos sintéticos: {sum(twin_counts)}",
        f"- Asimetría temporal mediana (subida/total): real "
        f"{report['asym_time_median_real']} vs gemelos {report['asym_time_median_twin']}",
        "\n| k | silueta real | silueta gemelo | margen |",
        "|---|---|---|---|",
    ]
    for k in sorted(sil_real):
        lines.append(
            f"| {k} | {sil_real[k]:.4f} | {sil_twin.get(k, float('nan')):.4f} "
            f"| {verdict_margin.get(k, float('nan')):+.4f} |"
        )
    lines.append(f"\n**Veredicto preliminar: {report['veredicto_preliminar']}**")
    gcs.upload_text("\n".join(lines), "reports/mountains_h13.md")

    for k in sorted(sil_real):
        print(
            f"[mountains] k={k}: real {sil_real[k]:.4f} vs twin "
            f"{sil_twin.get(k, float('nan')):.4f} (margen {verdict_margin.get(k, 0):+.4f})"
        )
    print(f"[mountains] {report['veredicto_preliminar']}")
    return 0


__all__ = [
    "Pivot",
    "catalog_series",
    "mountains_from_pivots",
    "shape_vector",
    "silhouette_by_k",
    "synthetic_twin",
    "zigzag_pivots",
]

if __name__ == "__main__":
    sys.exit(main())
