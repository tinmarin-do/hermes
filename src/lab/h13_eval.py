"""h13_eval — vara §8.1 del arco H13 (aprobada por Erika 2026-07-13, pre-registrada).

Aplica sobre puntos económicos de window_check (40 ventanas 28d, seed 42), en
retorno NETO ABSOLUTO (ya no exceso vs canasta — el objetivo del arco es retorno
absoluto). Marco temporal de Erika: 2021 = estrés; veredicto principal 2022+.

W1 economía moderna · W2 consistencia anual · W3 estrés 2021 · W4 energía cinética.
La vara NO se ablanda post-resultado.
"""

from typing import Any

import numpy as np
import pandas as pd

BAR = {
    "w1_mean_min": 1.0,  # % por ventana, 2022+
    "w2_year_min": -1.5,  # peor año 2022-2025
    "w3_2021_min": -3.0,  # estrés
}

# costos pre-registrados §13.3 (Binance USDT-M futures)
TAKER = 0.0005
ROUNDTRIP = 2 * TAKER  # entrada + salida sobre gross
FUNDING_28D = 0.0084  # 0.01%/8h × 84 periodos — solo costo, jamás crédito
FUNDING_BUFFER = 0.001  # libro neutral: buffer conservador por ventana
SLIPPAGE_SENS = 0.001  # +10bps roundtrip, solo reporte de sensibilidad


def apply_h13_bar(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Veredicto §8.1 sobre una lista de ventanas {t0, net_pct, bench_pct}."""
    df = pd.DataFrame(windows)
    df["year"] = pd.to_datetime(df["t0"]).dt.year
    modern = df[df["year"] >= 2022]
    y21 = df[df["year"] == 2021]["net_pct"]
    by_year = {int(y): round(float(g["net_pct"].mean()), 3) for y, g in modern.groupby("year")}
    down = modern[modern["bench_pct"] < 0]

    out: dict[str, Any] = {
        "n_windows": len(df),
        "n_modern": len(modern),
        "net_median_modern": round(float(modern["net_pct"].median()), 3),
        "net_mean_modern": round(float(modern["net_pct"].mean()), 3),
        "net_std_modern": round(float(modern["net_pct"].std()), 3),
        "by_year_modern": by_year,
        "net_mean_2021": round(float(y21.mean()), 3) if len(y21) else None,
        "n_down_modern": len(down),
        "net_median_when_down": round(float(down["net_pct"].median()), 3) if len(down) else None,
        "bar": dict(BAR),
    }
    out["w1"] = bool(out["net_median_modern"] > 0 and out["net_mean_modern"] >= BAR["w1_mean_min"])
    out["w2"] = bool(all(v >= BAR["w2_year_min"] for v in by_year.values()))
    out["w3"] = bool(out["net_mean_2021"] is None or out["net_mean_2021"] >= BAR["w3_2021_min"])
    out["w4"] = bool(out["net_median_when_down"] is not None and out["net_median_when_down"] >= 0)
    out["verdict"] = bool(out["w1"] and out["w2"] and out["w3"] and out["w4"])
    return out


def vol_scaled_signs(
    signs: pd.Series, sigma_daily: pd.Series, sigma_target_ann: float = 0.25, gross_cap: float = 1.0
) -> pd.Series:
    """Pesos TSMOM canónicos: signo × (σ_target/σ_i), repartidos y con tope de gross.

    signs ∈ {−1, 0, +1} por símbolo; sigma_daily = std diaria (20d). Los símbolos
    sin señal o sin vol válida pesan 0. Gross total ≤ gross_cap (sin apalancar).
    """
    tgt_daily = sigma_target_ann / np.sqrt(365.0)
    ok = signs.notna() & sigma_daily.notna() & (sigma_daily > 0) & (signs != 0)
    w = pd.Series(0.0, index=signs.index)
    if not ok.any():
        return w
    w[ok] = signs[ok] * (tgt_daily / sigma_daily[ok])
    w /= int(ok.sum())
    gross = float(w.abs().sum())
    if gross > gross_cap:
        w *= gross_cap / gross
    return w


def tsmom_window_economics(day: pd.DataFrame, w: pd.Series) -> dict[str, Any]:
    """Un punto económico TSMOM: hold 28d, fees roundtrip sobre gross, funding
    conservador sobre |net exposure| (costo siempre, crédito jamás)."""
    gross = float(w.abs().sum())
    net_exp = float(w.sum())
    ret = float((w * day.loc[w.index, "fwd_ret_24h_mxn"]).sum())
    net = ret - ROUNDTRIP * gross - FUNDING_28D * abs(net_exp)
    bench = float(day["fwd_ret_24h_mxn"].mean()) - ROUNDTRIP
    return {
        "net_pct": round(net * 100, 4),
        "bench_pct": round(bench * 100, 4),
        "gross": round(gross, 4),
        "net_exposure": round(net_exp, 4),
        "n_long": int((w > 0).sum()),
        "n_short": int((w < 0).sum()),
    }


def spread_leg_weights(day: pd.DataFrame, k: int, mode: str) -> tuple[pd.Series, pd.Series]:
    """Piernas del libro L/S: top-k por p (larga) y bottom-k (corta), 0.5 de gross
    cada una. mode 'ew' = equiponderada; 'ivol' = inverse-vol dentro de la pierna."""
    ranked = day.sort_values("p", ascending=False)
    top, bot = ranked.head(k), ranked.tail(k)

    def _leg(sub: pd.DataFrame) -> pd.Series:
        if mode == "ivol":
            iv = 1.0 / sub["sigma20"].clip(lower=1e-6)
            return 0.5 * iv / iv.sum()
        return pd.Series(0.5 / len(sub), index=sub.index)

    return _leg(top), _leg(bot)


def spread_window_economics(
    day: pd.DataFrame, w_long: pd.Series, w_short: pd.Series
) -> dict[str, Any]:
    """Punto económico del libro neutral: gross 1.0, net 0, costos §13.3."""
    long_ret = float((w_long * day.loc[w_long.index, "fwd_ret_24h_mxn"]).sum())
    short_ret = -float((w_short * day.loc[w_short.index, "fwd_ret_24h_mxn"]).sum())
    gross = float(w_long.sum() + w_short.sum())
    net = long_ret + short_ret - ROUNDTRIP * gross - FUNDING_BUFFER
    bench = float(day["fwd_ret_24h_mxn"].mean()) - ROUNDTRIP
    return {
        "net_pct": round(net * 100, 4),
        "bench_pct": round(bench * 100, 4),
        "long_leg_pct": round(long_ret * 100, 4),
        "short_leg_pct": round(short_ret * 100, 4),
        "gross": round(gross, 4),
        "n_universe": int(len(day)),
    }
