"""Split híbrido 80/20 pre-registrado (decisión #9, arco H11).

Sobre el sample de ITERACIÓN (el slice de confirmación queda FUERA, ver DESIGN_H11):
  (a) bloques temporales contiguos MENSUALES sorteados a validation (~20% de los
      bloques), purga 1d + embargo 5d en cada frontera, K=5 sorteos → F1 media±σ;
  (b) corte temporal puro: último 20% cronológico, misma purga/embargo.
La meta F1≥0.60 debe cumplirse en (a) Y (b). Prohibido el split aleatorio por filas.
Los splits operan sobre FECHAS (pooled): la purga cruza símbolos por construcción.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

PURGE_DAYS = 1
EMBARGO_DAYS = 5
VAL_FRACTION = 0.20
K_DRAWS = 5
CONFIRMATION_FRACTION = 0.15  # último 15% del histórico = slice one-shot (firewall)


@dataclass
class Split:
    name: str
    train_dates: pd.DatetimeIndex
    val_dates: pd.DatetimeIndex


def partitions(dates: pd.DatetimeIndex) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """(iteración, confirmación): el último 15% del rango es INTOCABLE (one-shot)."""
    dates = dates.sort_values().unique()
    cut = dates[int(len(dates) * (1 - CONFIRMATION_FRACTION))]
    return dates[dates < cut], dates[dates >= cut]


def _exclude_around(
    dates: pd.DatetimeIndex, val_blocks: list[tuple[pd.Timestamp, pd.Timestamp]]
) -> pd.DatetimeIndex:
    """Train = fechas fuera de [ini−purga, fin+embargo] de todo bloque de validation."""
    mask = np.ones(len(dates), dtype=bool)
    for start, end in val_blocks:
        lo = start - pd.Timedelta(days=PURGE_DAYS)
        hi = end + pd.Timedelta(days=EMBARGO_DAYS)
        mask &= ~((dates >= lo) & (dates <= hi))
    return dates[mask]


def hybrid_splits(iteration_dates: pd.DatetimeIndex, seed: int = 42) -> list[Split]:
    """K sorteos por bloques mensuales + corte temporal puro. Determinista por seed."""
    dates = pd.DatetimeIndex(iteration_dates).sort_values().unique()
    months = pd.PeriodIndex(dates, freq="M").unique().sort_values()
    n_val_months = max(1, round(len(months) * VAL_FRACTION))
    rng = np.random.default_rng(seed)

    out: list[Split] = []
    for k in range(K_DRAWS):
        chosen = rng.choice(len(months), size=n_val_months, replace=False)
        blocks = []
        val_mask = np.zeros(len(dates), dtype=bool)
        for i in sorted(chosen):
            m = months[i]
            in_month = (dates >= m.start_time) & (dates <= m.end_time)
            val_mask |= in_month
            blocks.append((m.start_time, m.end_time))
        out.append(
            Split(
                name=f"block_draw_{k}",
                train_dates=_exclude_around(dates[~val_mask], blocks),
                val_dates=dates[val_mask],
            )
        )

    # corte temporal puro: último 20% cronológico
    cut = dates[int(len(dates) * (1 - VAL_FRACTION))]
    val = dates[dates >= cut]
    out.append(
        Split(
            name="temporal_holdout",
            train_dates=_exclude_around(dates[dates < cut], [(val.min(), val.max())]),
            val_dates=val,
        )
    )
    return out
