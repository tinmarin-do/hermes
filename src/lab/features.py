"""Catálogo de variables candidatas H11 — cómputo causal + racional económico.

Regla de coherencia de ventanas (DESIGN_H11 §4): el information set observa
semanas/meses para predecir 1 día. Todo cómputo usa SOLO data ≤ t (rolling
windows que terminan en t). El canary anti-leakage del estudio verifica esto.

Entrada: panel largo (symbol, ts) con barras diarias (open/high/low/close/volume)
ordenado por symbol,ts. Las cross-seccionales pivotean sobre ts.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Candidate:
    name: str
    group: str
    rationale: str  # racional económico — obligatorio (sense first)
    fn: Callable[[pd.DataFrame], pd.Series] = field(repr=False)
    min_lookback_days: int = 0  # ventana efectiva de observación


def _g(df: pd.DataFrame, col: str = "close"):
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
            return H
        except Exception:  # noqa: BLE001
            return np.nan

    return x.rolling(window).apply(lambda a: h(a.values), raw=False)


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
                fn=lambda df, d=d: _ret(df, d),
                min_lookback_days=d,
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
