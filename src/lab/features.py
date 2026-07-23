"""Catálogo de variables candidatas H11 — cómputo causal + racional económico.

Regla de coherencia de ventanas (DESIGN_H11 §4): el information set observa
semanas/meses para predecir 1 día. Todo cómputo usa SOLO data ≤ t (rolling
windows que terminan en t). El canary anti-leakage del estudio verifica esto.

Entrada: panel largo (symbol, ts) con barras diarias (open/high/low/close/volume)
ordenado por symbol,ts. Las cross-seccionales pivotean sobre ts.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from pandas.core.groupby.generic import SeriesGroupBy


@dataclass
class Candidate:
    name: str
    group: str
    rationale: str  # racional económico — obligatorio (sense first)
    fn: Callable[[pd.DataFrame], pd.Series] = field(repr=False)
    min_lookback_days: int = 0  # ventana efectiva de observación


def _g(df: pd.DataFrame, col: str = "close") -> "SeriesGroupBy":
    return df.groupby("symbol", observed=True)[col]


def _ret(df: pd.DataFrame, days: int) -> pd.Series:
    return _g(df).pct_change(days)


def _zscore(s: pd.Series, df: pd.DataFrame, window: int = 60) -> pd.Series:
    grp = s.groupby(df["symbol"], observed=True)
    mu = grp.transform(lambda x: x.rolling(window, min_periods=window // 2).mean())
    sd = grp.transform(lambda x: x.rolling(window, min_periods=window // 2).std())
    return (s - mu) / sd


def _cross(df: pd.DataFrame, values: pd.Series, agg: str) -> pd.Series:
    """Estadístico cross-seccional por fecha, alineado de vuelta al panel largo."""
    wide = values.to_frame("v").assign(ts=df["ts"], symbol=df["symbol"])
    per_ts = wide.groupby("ts")["v"].transform(agg)
    return per_ts


def _rolling_hurst_series(x: pd.Series, window: int = 100) -> pd.Series:
    from hurst import compute_Hc

    def h(arr: np.ndarray) -> float:
        try:
            H, _, _ = compute_Hc(arr, kind="price", simplified=True)
            return float(H)
        except Exception:  # noqa: BLE001
            return float("nan")

    return x.rolling(window).apply(lambda a: h(a.values), raw=False)


# ── conjunto v1 APROBADO (gate D1, Erika 2026-07-12) ──────────────────────────
# Evidencia: dossier reports/feature_dossier.md (sample 8,570 filas, confirmación
# excluida). abs_ret_1d se deriva de la forma de U del decil de ret_1d (D1 47% /
# D10 40% vs centro 33%): una logística lineal promediaría la U a cero — la
# magnitud entra como variable propia (pierna vol-clustering del reversal).
FEATURE_SET_V1 = [
    "ret_1d",  # reversal per-symbol (IC −0.048, p=9e-6)
    "abs_ret_1d",  # magnitud del movimiento de ayer (U-shape del dossier)
    "btc_ret_1d",  # lead-lag BTC→alts (IC −0.056, la más fuerte)
    "rv_20d",  # carrier: y-rate 29→45% monótona, IC direccional nulo
    "hl_range_z30",  # expansión de rango (IC +0.041, p=2e-4)
    "hurst_100d",  # conditioner de régimen (débil p=0.26 — a prueba, sale en v2 si no aporta)
]

# Conjunto v2 — label rel_median (enmienda §9), gate aprobado por Erika 2026-07-12
# ("VAMOS!"). Evidencia: dossier v2 (reports/feature_dossier_v2_relmedian.md, IC
# contra retorno RELATIVO — el beta no puntúa). El espacio relativo INVIERTE señales
# del absoluto: el "reversal" de ret_* era beta (ahora momentum relativo +), y la vol
# pasa de carrier mecánico a anomalía low-vol cross-seccional (−, monótona 57→48%).
# Fuera: breadth_20d (constante por día — no rankea intradía; su IC era artefacto),
# rel_ret_5d (n.s. — lo predictivo de ret_5d es su componente de mercado vía beta),
# hurst_100d (muere por 2ª vez — fuera definitivo), dow/quincena/usdmxn (muertas).
FEATURE_SET_V2 = [
    "ret_2d",  # momentum relativo corto (IC +0.028, p=0.009; mejor de su cluster)
    "abs_ret_1d",  # calma ayer → outperformance relativa (IC −0.035, p=0.001)
    "btc_ret_1d",  # catch-up de beta tras BTC-up (IC +0.033, p=0.002; deciles 50→54%)
    "rv_20d",  # low-vol cross-seccional (IC −0.054, p<1e-4; 57→48% monótona)
    "hl_range",  # rango intradía de ayer (IC −0.056, la más fuerte; ~rv_20d < 0.7)
]

# Sets H12 por horizonte — gate cerrado (Erika 2026-07-12, DESIGN_H12 §8).
# Regla dura lookback ≥ H; evidencia: dossiers feature_dossier_v2_relmedian_h{3,7,14}
# (el IC del momentum CRECE con H: ret_63d +0.039/+0.041/+0.080; rv_20d vive en los 3).
FEATURE_SETS_H12 = {
    3: ["rv_20d", "ret_5d", "ret_21d", "ret_63d"],
    7: ["rv_20d", "ret_10d", "ret_21d", "ret_63d"],
    14: ["rv_20d", "ret_21d", "ret_63d"],
}


# ── registro de candidatas ─────────────────────────────────────────────────────
def build_candidates() -> list[Candidate]:
    C: list[Candidate] = []

    # Grupo 1 — retornos cortos (momentum/reversal de corto plazo)
    for d in (1, 2, 3, 5, 10):
        C.append(
            Candidate(
                name=f"ret_{d}d",
                group="1_retornos",
                rationale=(
                    f"Retorno {d}d: el IC negativo hallado en H9 sugiere REVERSAL de corto "
                    "plazo en la magnitud; a horizonte 1d el signo/magnitud reciente es el "
                    "candidato más directo (continuación o reversión — el estudio decide)."
                ),
                fn=partial(_ret, days=d),
                min_lookback_days=d,
            )
        )
    # Formación larga (candidatas 2026-07-12, post-tanda 4): los lookbacks CANÓNICOS
    # del momentum cross-seccional (1 y 3 meses, literatura de factor investing y
    # crypto momentum). Sin probar contra NINGÚN label relativo — ret_10d salió n.s.
    # pero la formación mensual es otra fisiología (rebalanceo institucional, drift
    # post-narrativa). Cumplen mejor la regla observación >> horizonte de Erika.
    for d in (21, 63):
        C.append(
            Candidate(
                name=f"ret_{d}d",
                group="1_retornos",
                rationale=(
                    f"Momentum de formación {d}d ({'1 mes' if d == 21 else '3 meses'}): "
                    "lookback canónico del momentum cross-seccional; en relativo, los "
                    "ganadores de formación mensual tienden a persistir (o revertir — "
                    "el estudio decide; ret_10d fue n.s., esta escala es distinta)."
                ),
                fn=partial(_ret, days=d),
                min_lookback_days=d,
            )
        )
    C.append(
        Candidate(
            name="abs_ret_1d",
            group="1_retornos",
            rationale="Magnitud del retorno de ayer |ret_1d|: el decil del dossier mostró "
            "forma de U — ambos extremos elevan p(y=1) (vol clustering). La logística "
            "necesita la magnitud como variable aparte para no promediar la U a cero.",
            fn=lambda df: _ret(df, 1).abs(),
            min_lookback_days=1,
        )
    )
    C.append(
        Candidate(
            name="ret_5d_z60",
            group="1_retornos",
            rationale="Retorno 5d normalizado por su régimen local (z 60d): separa un +5% "
            "'normal en este símbolo' de un +5% extremo — el extremo es el que revierte.",
            fn=lambda df: _zscore(_ret(df, 5), df, 60),
            min_lookback_days=60,
        )
    )

    # Grupo 2 — estructura del rango/volumen diario
    C.append(
        Candidate(
            name="hl_range",
            group="2_intradia",
            rationale="Rango (high−low)/close del día: proxy de disputa intradía; rangos "
            "anchos anticipan continuación de volatilidad → más días |ret|>1%.",
            fn=lambda df: (df["high"] - df["low"]) / df["close"],
            min_lookback_days=1,
        )
    )
    C.append(
        Candidate(
            name="hl_range_z30",
            group="2_intradia",
            rationale="Rango normalizado vs su historia 30d: la EXPANSIÓN de rango (no su "
            "nivel) es la señal de cambio de régimen de vol.",
            fn=lambda df: _zscore((df["high"] - df["low"]) / df["close"], df, 30),
            min_lookback_days=30,
        )
    )
    C.append(
        Candidate(
            name="vol_z30",
            group="2_intradia",
            rationale="Volumen z 30d: volumen anómalo = información entrando al mercado; "
            "los breakouts con volumen sostienen; sin volumen, revierten.",
            fn=lambda df: _zscore(df["volume"], df, 30),
            min_lookback_days=30,
        )
    )
    C.append(
        Candidate(
            name="rv_20d",
            group="2_intradia",
            rationale="Vol realizada 20d de retornos diarios: p(|ret|>1%) escala casi "
            "mecánicamente con la vol — es el 'carrier' del target y todo lo demás se "
            "lee condicionado a ella.",
            fn=lambda df: (
                _g(df)
                .pct_change()
                .groupby(df["symbol"], observed=True)
                .transform(lambda x: x.rolling(20, min_periods=10).std())
            ),
            min_lookback_days=20,
        )
    )

    # Grupo 3 — cross-seccionales (el eje nuevo del universo ampliado)
    C.append(
        Candidate(
            name="rel_ret_5d",
            group="3_cross",
            rationale="Retorno 5d vs la mediana del universo: fuerza relativa — separa "
            "movimiento idiosincrático de beta de mercado (el mercado entero subiendo "
            "no dice qué símbolo liderará mañana).",
            fn=lambda df: _ret(df, 5) - _cross(df, _ret(df, 5), "median"),
            min_lookback_days=5,
        )
    )
    C.append(
        Candidate(
            name="btc_ret_1d",
            group="3_cross",
            rationale="Retorno 1d de BTC como feature de TODOS (lead-lag): BTC mueve el "
            "risk-on/off del asset class y las alts siguen con rezago de horas-días.",
            fn=lambda df: df["ts"].map(
                df.loc[df["symbol"] == "BTC"].set_index("ts")["close"].pct_change()
            ),
            min_lookback_days=1,
        )
    )
    C.append(
        Candidate(
            name="breadth_20d",
            group="3_cross",
            rationale="% del universo sobre su MA20: amplitud del rally — un mercado con "
            "breadth alto sostiene continuación; rallies estrechos se agotan.",
            fn=lambda df: _cross(
                df,
                (
                    df["close"] > _g(df).transform(lambda x: x.rolling(20, min_periods=10).mean())
                ).astype(float),
                "mean",
            ),
            min_lookback_days=20,
        )
    )

    # Grupo 4 — régimen ligero diario
    C.append(
        Candidate(
            name="hurst_100d",
            group="4_regimen",
            rationale="Hurst 100d sobre precio diario: >0.5 trending / <0.5 mean-reverting "
            "— el MISMO clasificador de régimen del campeón, a frecuencia diaria. Decide "
            "si el momentum corto se lee como continuación o como reversión.",
            fn=lambda df: _g(df).transform(lambda x: _rolling_hurst_series(x, 100)),
            min_lookback_days=100,
        )
    )
    C.append(
        Candidate(
            name="ewma_vol_20",
            group="4_regimen",
            rationale="Vol EWMA λ=0.94 (RiskMetrics) de retornos diarios: régimen de vol "
            "reactivo sin el costo de refitear GARCH; hermana del vol-targeting H10.3.",
            fn=lambda df: (
                _g(df)
                .pct_change()
                .groupby(df["symbol"], observed=True)
                .transform(lambda x: x.ewm(alpha=0.06, min_periods=10).std())
            ),
            # 75d ≈ 99.999% de la memoria efectiva del EWMA α=0.06 (canary local)
            min_lookback_days=75,
        )
    )

    # Grupo 5 — calendario (flujos MXN)
    C.append(
        Candidate(
            name="dow",
            group="5_calendario",
            rationale="Día de la semana (0-6): efectos de fin de semana en cripto están "
            "documentados (liquidez retail vs institucional); en MXN se suma el ciclo "
            "de nómina local.",
            fn=lambda df: pd.to_datetime(df["ts"]).dt.dayofweek.astype(float),
            min_lookback_days=0,
        )
    )
    C.append(
        Candidate(
            name="quincena",
            group="5_calendario",
            rationale="Flag de quincena mexicana (días 1-3 y 14-17): flujo de nómina que "
            "entra a Bitso en pesos — hipótesis de presión compradora local.",
            fn=lambda df: (
                pd.to_datetime(df["ts"]).dt.day.isin([1, 2, 3, 14, 15, 16, 17]).astype(float)
            ),
            min_lookback_days=0,
        )
    )

    # Grupo 6 — FX (riesgo peso)
    C.append(
        Candidate(
            name="usdmxn_ret_5d",
            group="6_fx",
            rationale="Retorno 5d del USDMXN: el peso es termómetro EM de risk-on/off; "
            "además el label ESTÁ en MXN — la depreciación del peso empuja mecánicamente "
            "los precios cripto-MXN hacia el umbral del +1%.",
            fn=lambda df: _g(df, "usdmxn").pct_change(5) if "usdmxn" in df.columns else np.nan,
            min_lookback_days=5,
        )
    )
    return C


def compute_matrix(panel: pd.DataFrame, candidates: list[Candidate] | None = None) -> pd.DataFrame:
    """Panel largo → matriz de features causales (una columna por candidata)."""
    panel = panel.sort_values(["symbol", "ts"]).reset_index(drop=True)
    out = panel[["source", "symbol", "ts", "y", "fwd_ret_24h_mxn"]].copy()
    for c in candidates or build_candidates():
        out[c.name] = c.fn(panel)
    return out
