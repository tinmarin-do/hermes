"""harvest_structure — EDA de estructura del vaivén diario (H14 F2a).

Estadísticos de anti-persistencia sobre el corpus anti-supervivencia
(`datasets/market_daily_v1.parquet`): variance ratios Lo-MacKinlay con z* robusto
a heterocedasticidad y wild bootstrap (Kim 2006, Rademacher), ρ₁ con SE robusto,
persistencia de signo, estratos de liquidez point-in-time, gemelos de permutación,
mapa liquidez×vol (test de Zaremba 2021), espécimen de la canasta whitelist y
niveles de funding realizado.

**Sin P&L, sin costos, sin veredicto económico** — descriptivo, NO cuenta al DSR
(DESIGN_H14 §4). El fixmix y su test de invarianza a permutación viven en F3 (si
F2a pasa); aquí solo estructura. Falsadores pre-registrados (§5.1-§5.2):
  H-A: IC90 de la mediana del estrato ejecutable de VR(28) enteramente ≥ 1.0,
       o IC90 de la mediana de ρ₁ enteramente ≥ 0, en 2022+  → falsificada.
  H-C: ídem VR(28) en 2024-07-01→2026-06-30 (ventana fija)   → falsificada.
IC por bootstrap de bloques SOBRE FECHAS (n_eff≈1.25 por corr cross-seccional).

Convenciones (§5.6): VR sobre log-retornos, estimador overlapping con corrección
de sesgo, decisión por IC jamás por punto. Seed 42. Corte 2026-06-30 (fijo §2).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.harvest_structure"
Escribe reports/h14_structure.{json,md}
"""

import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs

SEED = 42
QS = (2, 5, 10, 28)
Q_VERDICT = 28  # §5.1: el reloj contra el que se cosecharía
BLOCK_LEN = 56  # bootstrap de bloques: 2×q para diluir bordes
N_BOOT = 500
N_WILD = 200
N_PERM = {2: 20, 5: 20, 10: 100, 28: 100}  # §5.5
MIN_OBS = 100
ENTRY_DAYS = 60  # §6: un símbolo entra al universo tras 60 días de historia
START = pd.Timestamp("2021-01-01")
CUTOFF = pd.Timestamp("2026-06-30")
PERIODS = {
    "full": (pd.Timestamp("2021-01-01"), CUTOFF),
    "modern": (pd.Timestamp("2022-01-01"), CUTOFF),  # veredicto H-A (§5.1, casa 2022+)
    "recent": (pd.Timestamp("2024-07-01"), CUTOFF),  # veredicto H-C (§5.2, fija)
}
EXECUTABLE_QUINTILES = {4, 5}  # top-40% (§6, congelado en pre-registro)
WHITELIST = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT", "XRPUSDT")


# ---------- estimadores ----------

def variance_ratio(x: np.ndarray, q: int, with_z: bool = True) -> tuple[float, float]:
    """VR(q) Lo-MacKinlay overlapping con corrección de sesgo + z* robusto a
    heterocedasticidad (Lo & MacKinlay 1988). x = log-retornos (NaN tolerados)."""
    x = x[~np.isnan(x)]
    t = len(x)
    if t < max(4 * q, MIN_OBS):
        return float("nan"), float("nan")
    mu = x.mean()
    d = x - mu
    s1 = float(d @ d) / (t - 1)
    if s1 <= 0:
        return float("nan"), float("nan")
    c = np.concatenate(([0.0], np.cumsum(x)))
    xq = c[q:] - c[:-q]  # sumas de q consecutivos (t-q+1 ventanas overlapping)
    m = q * (t - q + 1) * (1 - q / t)
    sq = float(np.sum((xq - q * mu) ** 2)) / m
    vr = sq / s1
    if not with_z:
        return vr, float("nan")
    denom = float(d @ d) ** 2
    theta = 0.0
    for k in range(1, q):
        dk = float(np.sum(d[k:] ** 2 * d[:-k] ** 2)) / denom
        theta += (2 * (q - k) / q) ** 2 * dk
    z = (vr - 1) / np.sqrt(theta) if theta > 0 else float("nan")
    return vr, float(z)


def wild_bootstrap_pvalue(
    x: np.ndarray, q: int, rng: np.random.Generator, reps: int = N_WILD
) -> float:
    """p-valor bilateral de VR(q)≠1 bajo wild bootstrap de Kim (2006), pesos
    Rademacher (preservan |x| exacto — el nulo mantiene la heterocedasticidad
    y destruye la estructura temporal)."""
    x = x[~np.isnan(x)]
    if len(x) < max(4 * q, MIN_OBS):
        return float("nan")
    vr_obs, _ = variance_ratio(x, q, with_z=False)
    hits = 0
    for _ in range(reps):
        eta = rng.choice([-1.0, 1.0], size=len(x))
        vr_b, _ = variance_ratio(x * eta, q, with_z=False)
        if abs(vr_b - 1) >= abs(vr_obs - 1):
            hits += 1
    return (hits + 1) / (reps + 1)


def rho1_robust(x: np.ndarray) -> tuple[float, float]:
    """ρ₁ con SE robusto a heterocedasticidad (White sobre la regresión AR(1))."""
    x = x[~np.isnan(x)]
    if len(x) < MIN_OBS:
        return float("nan"), float("nan")
    d = x - x.mean()
    num = float(d[1:] @ d[:-1])
    den = float(d[:-1] @ d[:-1])
    if den <= 0:
        return float("nan"), float("nan")
    rho = num / den
    resid = d[1:] - rho * d[:-1]
    se = float(np.sqrt(np.sum(resid**2 * d[:-1] ** 2))) / den
    return rho, se


def sign_persistence(x: np.ndarray) -> float:
    """P(sign(r_t) == sign(r_{t-1})) sobre pares consecutivos válidos y no-cero
    (misma definición que trend_study a h=1)."""
    x = x[~np.isnan(x)]
    a, b = x[1:], x[:-1]
    ok = (a != 0) & (b != 0)
    if int(ok.sum()) < MIN_OBS:
        return float("nan")
    return float((np.sign(a[ok]) == np.sign(b[ok])).mean())


# ---------- estratos point-in-time ----------

def month_stratum(panel: pd.DataFrame) -> pd.DataFrame:
    """Quintil de liquidez por símbolo×mes, SIN lookahead: el quintil del mes m
    usa el quote-volume mediano rolling 30d con datos hasta el fin del mes m-1.
    Devuelve DataFrame(symbol, month, quintile)."""
    p = panel.sort_values(["symbol", "ts"]).copy()
    p["liq"] = (
        p.groupby("symbol")["quote_volume"]
        .transform(lambda s: s.rolling(30, min_periods=30).median())
    )
    p["month"] = p["ts"].dt.to_period("M")
    # última métrica disponible de cada mes → aplica al mes SIGUIENTE
    last = p.groupby(["symbol", "month"])["liq"].last().reset_index()
    last["month"] = last["month"] + 1
    last = last.dropna(subset=["liq"])
    out = []
    for month, g in last.groupby("month"):
        if len(g) < 5:
            continue
        q = pd.qcut(g["liq"].rank(method="first"), 5, labels=False) + 1
        out.append(pd.DataFrame({"symbol": g["symbol"], "month": month, "quintile": q}))
    return pd.concat(out, ignore_index=True)


def majority_quintile(strata: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    """Quintil mayoritario por símbolo dentro del periodo (regla operativa del
    falsador: pertenencia mensual → asignación por mayoría, documentada)."""
    m0, m1 = t0.to_period("M"), t1.to_period("M")
    sub = strata[(strata["month"] >= m0) & (strata["month"] <= m1)]
    if sub.empty:
        return pd.Series(dtype="int64")
    return (
        sub.groupby("symbol")["quintile"]
        .agg(lambda s: int(s.value_counts().idxmax()))
        .astype("int64")
    )


# ---------- bootstrap de bloques sobre fechas ----------

def _vr_cols(mat: np.ndarray, q: int) -> np.ndarray:
    return np.array([variance_ratio(mat[:, j], q, with_z=False)[0] for j in range(mat.shape[1])])


def _rho_cols(mat: np.ndarray) -> np.ndarray:
    return np.array([rho1_robust(mat[:, j])[0] for j in range(mat.shape[1])])


def block_bootstrap_median(
    mat: np.ndarray,
    stat: str,
    q: int,
    rng: np.random.Generator,
    n_boot: int = N_BOOT,
    block_len: int = BLOCK_LEN,
) -> dict[str, float]:
    """IC90 de la MEDIANA cross-seccional del estadístico, re-muestreando FECHAS
    en bloques móviles (preserva la dependencia cross-seccional — n_eff≈1.25).
    mat: matriz T×N de log-retornos (NaN fuera de vida del símbolo)."""
    t = mat.shape[0]
    if t < block_len * 2:
        return {"median": float("nan"), "lo90": float("nan"), "hi90": float("nan")}
    point_stats = _vr_cols(mat, q) if stat == "vr" else _rho_cols(mat)
    point = float(np.nanmedian(point_stats))
    n_blocks = int(np.ceil(t / block_len))
    medians = np.empty(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, t - block_len + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_len) for s in starts])[:t]
        cols = _vr_cols(mat[idx], q) if stat == "vr" else _rho_cols(mat[idx])
        medians[b] = np.nanmedian(cols)
    lo, hi = np.nanquantile(medians, [0.05, 0.95])
    return {"median": round(point, 4), "lo90": round(float(lo), 4), "hi90": round(float(hi), 4)}


# ---------- gemelos ----------

def permutation_twin_residual(
    x: np.ndarray, q: int, rng: np.random.Generator, reps: int
) -> float:
    """VR_real(q) − mediana(VR_permutado(q)). A f=1 sería 0 por álgebra (la
    invarianza se testea en unit tests de F3, donde vive el fixmix); aquí solo
    informa f≥2 (§5.5)."""
    x = x[~np.isnan(x)]
    if len(x) < max(4 * q, MIN_OBS):
        return float("nan")
    vr_real, _ = variance_ratio(x, q, with_z=False)
    twins = np.empty(reps)
    for r in range(reps):
        twins[r] = variance_ratio(rng.permutation(x), q, with_z=False)[0]
    return float(vr_real - np.median(twins))


def block_twin_residual(x: np.ndarray, rng: np.random.Generator, reps: int = 10) -> float:
    """Gemelo block-bootstrap 20d de la casa (mountains) — SOLO q=28 (§5.5):
    conserva clustering de vol y autocorr corta; el residuo es estructura lenta."""
    x = x[~np.isnan(x)]
    if len(x) < MIN_OBS + 28:
        return float("nan")
    vr_real, _ = variance_ratio(x, Q_VERDICT, with_z=False)
    block = 20
    n_blocks = int(np.ceil(len(x) / block))
    twins = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, len(x) - block + 1, size=n_blocks)
        xb = np.concatenate([x[s : s + block] for s in starts])[: len(x)]
        twins[r] = variance_ratio(xb, Q_VERDICT, with_z=False)[0]
    return float(vr_real - np.median(twins))


# ---------- panel ----------

def load_panel() -> pd.DataFrame:
    p = gcs.read_parquet("datasets/market_daily_v1.parquet")
    p["ts"] = pd.to_datetime(p["ts"])
    p = p[(p["ts"] >= START) & (p["ts"] <= CUTOFF) & (p["close"] > 0)]
    p = p.sort_values(["symbol", "ts"]).reset_index(drop=True)
    p["logret"] = p.groupby("symbol")["close"].transform(lambda s: np.log(s).diff())
    # regla de entrada §6: los primeros ENTRY_DAYS días de cada símbolo no son evaluables
    p["age"] = p.groupby("symbol").cumcount()
    p.loc[p["age"] < ENTRY_DAYS, "logret"] = np.nan
    return p.drop(columns="age")


def returns_matrix(
    panel: pd.DataFrame, symbols: list[str], t0: pd.Timestamp, t1: pd.Timestamp
) -> tuple[np.ndarray, list[str]]:
    sub = panel[(panel["ts"] >= t0) & (panel["ts"] <= t1) & panel["symbol"].isin(symbols)]
    wide = sub.pivot_table(index="ts", columns="symbol", values="logret", aggfunc="first")
    wide = wide.sort_index()
    keep = [c for c in wide.columns if wide[c].notna().sum() >= MIN_OBS]
    return wide[keep].to_numpy(), keep


def symbol_stats(x: np.ndarray, rng: np.random.Generator) -> dict[str, Any]:
    out: dict[str, Any] = {}
    xc = x[~np.isnan(x)]
    if len(xc) < MIN_OBS:
        return {"n": int(len(xc))}
    out["n"] = int(len(xc))
    out["sigma_d"] = round(float(np.std(xc, ddof=1)), 5)
    rho, se = rho1_robust(x)
    out["rho1"], out["rho1_se"] = round(rho, 4), round(se, 4)
    out["persistence"] = round(sign_persistence(x), 4)
    for q in QS:
        vr, z = variance_ratio(x, q)
        out[f"vr{q}"] = round(vr, 4) if np.isfinite(vr) else None
        out[f"vr{q}_z"] = round(z, 2) if np.isfinite(z) else None
    out["vr28_wild_p"] = round(wild_bootstrap_pvalue(x, Q_VERDICT, rng), 4)
    return out


# ---------- funding ----------

def funding_annualized(funding: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp) -> pd.Series:
    sub = funding[(funding["ts"] >= t0) & (funding["ts"] <= t1)]
    if sub.empty:
        return pd.Series(dtype="float64")

    def _ann(g: pd.DataFrame) -> float:
        days = int((g["ts"].max() - g["ts"].min()).days) + 1
        if days < 90:
            return float("nan")
        return float(g["funding_rate"].sum()) * 365.0 / days

    return sub.groupby("symbol").apply(_ann, include_groups=False).dropna()


# ---------- veredicto ----------

def apply_falsadores(
    modern_vr: dict[str, float], modern_rho: dict[str, float], recent_vr: dict[str, float]
) -> dict[str, Any]:
    """Falsadores §5.1/§5.2 tal como se pre-registraron: matan solo si el IC90
    completo queda del lado equivocado. La decisión es por IC, jamás por punto."""
    ha_killed_by_vr = modern_vr["lo90"] >= 1.0
    ha_killed_by_rho = modern_rho["lo90"] >= 0.0
    hc_killed = recent_vr["lo90"] >= 1.0
    ha_pass = not (ha_killed_by_vr or ha_killed_by_rho)
    hc_pass = not hc_killed
    return {
        "HA": {
            "pass": bool(ha_pass),
            "killed_by_vr28": bool(ha_killed_by_vr),
            "killed_by_rho1": bool(ha_killed_by_rho),
            "vr28_modern": modern_vr,
            "rho1_modern": modern_rho,
        },
        "HC": {"pass": bool(hc_pass), "vr28_recent": recent_vr},
        "advance_to_F3": bool(ha_pass and hc_pass),
    }


def main() -> int:
    t_start = datetime.now(UTC)
    rng = np.random.default_rng(SEED)
    panel = load_panel()
    funding = gcs.read_parquet("datasets/market_funding_v1.parquet")
    funding["ts"] = pd.to_datetime(funding["ts"])
    strata = month_stratum(panel)
    all_symbols = sorted(panel["symbol"].unique())
    print(f"[harvest_structure] panel {len(panel):,} filas · {len(all_symbols)} símbolos")

    report: dict[str, Any] = {
        "generated": t_start.isoformat(),
        "protocol": {
            "design": "DESIGN_H14_rebalancing_premium.md §5",
            "seed": SEED, "qs": list(QS), "q_verdict": Q_VERDICT,
            "n_boot": N_BOOT, "block_len": BLOCK_LEN, "n_wild": N_WILD,
            "executable_quintiles": sorted(EXECUTABLE_QUINTILES),
            "entry_days": ENTRY_DAYS, "cutoff": str(CUTOFF.date()),
            "nota": "descriptivo, NO cuenta al DSR; falsadores por IC90",
        },
        "panel": {
            "rows": int(len(panel)), "symbols": len(all_symbols),
            "first": str(panel["ts"].min().date()), "last": str(panel["ts"].max().date()),
        },
    }

    # --- estadísticos por símbolo y periodo (tabla maestra) ---
    per_symbol: dict[str, dict[str, Any]] = {}
    period_matrices: dict[str, tuple[np.ndarray, list[str]]] = {}
    for pname, (t0, t1) in PERIODS.items():
        mat, keep = returns_matrix(panel, all_symbols, t0, t1)
        period_matrices[pname] = (mat, keep)
        stats = {}
        for j, sym in enumerate(keep):
            stats[sym] = symbol_stats(mat[:, j], rng)
        per_symbol[pname] = stats
        print(f"[harvest_structure] {pname}: {len(keep)} símbolos evaluables")
    report["per_symbol"] = per_symbol

    # --- estrato ejecutable + falsadores (IC90 bootstrap de bloques) ---
    verdict_inputs = {}
    strata_summary: dict[str, Any] = {}
    for pname in ("modern", "recent"):
        t0, t1 = PERIODS[pname]
        mq = majority_quintile(strata, t0, t1)
        execu = sorted(mq[mq.isin(EXECUTABLE_QUINTILES)].index)
        mat, keep = returns_matrix(panel, execu, t0, t1)
        vr_ci = block_bootstrap_median(mat, "vr", Q_VERDICT, rng)
        rho_ci = block_bootstrap_median(mat, "rho", Q_VERDICT, rng)
        strata_summary[pname] = {
            "n_executable": len(keep),
            "vr28_median_ci90": vr_ci,
            "rho1_median_ci90": rho_ci,
        }
        verdict_inputs[pname] = (vr_ci, rho_ci)
        print(f"[harvest_structure] {pname} ejecutable n={len(keep)} vr28={vr_ci} rho1={rho_ci}")
    report["executable_stratum"] = strata_summary
    report["verdict"] = apply_falsadores(
        verdict_inputs["modern"][0], verdict_inputs["modern"][1], verdict_inputs["recent"][0]
    )

    # --- mapa liquidez×vol (test de Zaremba) ---
    mapa = []
    for pname in ("modern", "recent"):
        t0, t1 = PERIODS[pname]
        mq = majority_quintile(strata, t0, t1)
        stats = per_symbol[pname]
        sigmas = {s: v["sigma_d"] for s, v in stats.items() if v.get("sigma_d")}
        if not sigmas:
            continue
        terc = pd.qcut(pd.Series(sigmas).rank(method="first"), 3, labels=[1, 2, 3])
        for quint in (1, 2, 3, 4, 5):
            for t in (1, 2, 3):
                syms = [
                    s for s in sigmas
                    if mq.get(s) == quint and terc[s] == t
                ]
                vals28 = [stats[s]["vr28"] for s in syms if stats[s].get("vr28")]
                rhos = [stats[s]["rho1"] for s in syms if stats[s].get("rho1") is not None]
                if len(vals28) < 3:
                    continue
                mapa.append(
                    {
                        "period": pname, "liq_quintile": quint, "vol_tercile": int(t),
                        "n": len(vals28),
                        "vr28_median": round(float(np.median(vals28)), 4),
                        "rho1_median": round(float(np.median(rhos)), 4),
                        "sigma_median": round(float(np.median([sigmas[s] for s in syms])), 5),
                    }
                )
    report["map_liq_vol"] = mapa

    # --- gemelos (residuo real − sintético, por estrato ejecutable, modern) ---
    t0, t1 = PERIODS["modern"]
    mq = majority_quintile(strata, t0, t1)
    execu = sorted(mq[mq.isin(EXECUTABLE_QUINTILES)].index)
    mat, keep = returns_matrix(panel, execu, t0, t1)
    twins: dict[str, Any] = {}
    for q in QS:
        if q == 1:
            continue
        res = [permutation_twin_residual(mat[:, j], q, rng, N_PERM[q]) for j in range(len(keep))]
        res_a = np.array(res)
        twins[f"perm_residual_vr{q}_median"] = (
            round(float(np.nanmedian(res_a)), 4) if np.isfinite(res_a).any() else None
        )
    block_res = np.array([block_twin_residual(mat[:, j], rng) for j in range(len(keep))])
    twins["block20_residual_vr28_median"] = (
        round(float(np.nanmedian(block_res)), 4) if np.isfinite(block_res).any() else None
    )
    report["twins"] = twins

    # --- espécimen canasta whitelist (la observación de Erika) ---
    wl = panel[panel["symbol"].isin(WHITELIST)]
    simple = wl.pivot_table(index="ts", columns="symbol", values="logret", aggfunc="first")
    basket = np.log1p(np.expm1(simple).mean(axis=1, skipna=True)).dropna()
    wl_stats = {}
    for pname, (t0, t1) in PERIODS.items():
        x = basket[(basket.index >= t0) & (basket.index <= t1)].to_numpy()
        wl_stats[pname] = symbol_stats(x, rng)
    report["whitelist_basket_ew"] = wl_stats

    # --- funding realizado (niveles, sin veto) ---
    fund_summary = {}
    for pname, (t0, t1) in PERIODS.items():
        ann = funding_annualized(funding, t0, t1)
        mq = majority_quintile(strata, t0, t1)
        execu_syms = set(mq[mq.isin(EXECUTABLE_QUINTILES)].index)
        in_exec = ann[ann.index.isin(execu_syms)]
        fund_summary[pname] = {
            "n": int(len(ann)),
            "median_annualized": round(float(ann.median()), 4) if len(ann) else None,
            "executable_median_annualized": (
                round(float(in_exec.median()), 4) if len(in_exec) else None
            ),
        }
    report["funding_realized"] = fund_summary

    # --- por año (reporte, sin poder de veto) ---
    by_year: dict[str, Any] = {}
    for year in range(2021, 2027):
        t0 = pd.Timestamp(f"{year}-01-01")
        t1 = min(pd.Timestamp(f"{year}-12-31"), CUTOFF)
        mat, keep = returns_matrix(panel, all_symbols, t0, t1)
        if not keep:
            continue
        vr_arr = _vr_cols(mat, Q_VERDICT)
        rho_arr = _rho_cols(mat)
        by_year[str(year)] = {
            "n": len(keep),
            "vr28_median": round(float(np.nanmedian(vr_arr)), 4),
            "rho1_median": round(float(np.nanmedian(rho_arr)), 4),
        }
    report["by_year"] = by_year

    gcs.upload_json(report, "reports/h14_structure.json")

    v = report["verdict"]
    lines = [
        "# H14 F2a — estructura del vaivén (veredicto H-A / H-C)",
        f"\nGenerado {t_start.isoformat()} · protocolo §5 DESIGN_H14 · seed {SEED}\n",
        f"**H-A (2022+)**: {'PASA (no falsificada)' if v['HA']['pass'] else '❌ FALSIFICADA'} — "
        f"VR28 mediana {v['HA']['vr28_modern']['median']} "
        f"IC90 [{v['HA']['vr28_modern']['lo90']}, {v['HA']['vr28_modern']['hi90']}] · "
        f"ρ₁ mediana {v['HA']['rho1_modern']['median']} "
        f"IC90 [{v['HA']['rho1_modern']['lo90']}, {v['HA']['rho1_modern']['hi90']}]",
        f"\n**H-C (2024-07→2026-06)**: "
        f"{'PASA (no falsificada)' if v['HC']['pass'] else '❌ FALSIFICADA'} — "
        f"VR28 mediana {v['HC']['vr28_recent']['median']} "
        f"IC90 [{v['HC']['vr28_recent']['lo90']}, {v['HC']['vr28_recent']['hi90']}]",
        f"\n**Agregador §4**: avanza a F3 = {v['advance_to_F3']}",
        "\n## Por año (mediana universo completo)",
        "| año | n | VR28 | ρ₁ |",
        "|---|---|---|---|",
    ]
    for y, s in by_year.items():
        lines.append(f"| {y} | {s['n']} | {s['vr28_median']} | {s['rho1_median']} |")
    lines += [
        "\n## Mapa liquidez×vol (modern)",
        "| Q liq | T vol | n | VR28 | ρ₁ |",
        "|---|---|---|---|---|",
    ]
    for cell in [c for c in mapa if c["period"] == "modern"]:
        lines.append(
            f"| {cell['liq_quintile']} | {cell['vol_tercile']} | {cell['n']} "
            f"| {cell['vr28_median']} | {cell['rho1_median']} |"
        )
    gcs.upload_text("\n".join(lines), "reports/h14_structure.md")

    dt = (datetime.now(UTC) - t_start).total_seconds()
    print(
        f"[harvest_structure] veredicto: H-A pass={v['HA']['pass']} "
        f"H-C pass={v['HC']['pass']} → F3={v['advance_to_F3']} · {dt:.0f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
