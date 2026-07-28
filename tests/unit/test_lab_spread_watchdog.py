"""Tests del motor watchdog (H13 §14) — números a mano."""

import numpy as np
import pandas as pd
import pytest

from src.lab.h13_eval import FUNDING_BUFFER, ROUNDTRIP
from src.lab.spread_watchdog_backtest import leg_exit, spread_watchdog_economics, symbol_path

pytestmark = pytest.mark.unit


def _sym(ts0: str, closes: list[float], fx: float = 17.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.date_range(ts0, periods=len(closes)),
            "close": closes,
            "usdmxn": [fx] * len(closes),
        }
    )


def test_symbol_path_camina_dia_a_dia_desde_la_ancla() -> None:
    g = _sym("2024-01-01", [100, 110, 90, 130, 100])
    path = symbol_path(g, 0, 4)
    assert list(path["day"]) == [1, 2, 3, 4]
    assert np.allclose(path["cum_ret"], [0.10, -0.10, 0.30, 0.00])


def test_symbol_path_ajusta_por_fx() -> None:
    g = pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-01", periods=2),
            "close": [100.0, 110.0],
            "usdmxn": [17.0, 18.7],  # +10% FX el mismo día que +10% precio
        }
    )
    path = symbol_path(g, 0, 1)
    # (1.10)(1.10) - 1 = 0.21
    assert np.isclose(path["cum_ret"].iloc[0], 0.21)


def test_symbol_path_vacio_si_no_hay_dias_siguientes() -> None:
    g = _sym("2024-01-01", [100.0])
    path = symbol_path(g, 0, 4)
    assert path.empty


def test_leg_exit_largo_dispara_take_profit() -> None:
    path = pd.DataFrame({"day": [1, 2, 3, 4], "cum_ret": [0.05, -0.10, 0.30, 0.00]})
    ret, exit_day = leg_exit(path, side=1.0, sigma=0.03, k=1.0, h=4)
    assert exit_day == 1  # primer día que cruza ±0.03
    assert np.isclose(ret, 0.05)


def test_leg_exit_corto_invierte_el_signo() -> None:
    """Una pata corta gana cuando el precio CAE — el gatillo usa el retorno CON SIGNO."""
    path = pd.DataFrame({"day": [1, 2], "cum_ret": [-0.10, -0.20]})
    ret, exit_day = leg_exit(path, side=-1.0, sigma=0.03, k=1.0, h=2)
    # signed = -cum_ret = [0.10, 0.20] → dispara en day 1 (0.10 >= 0.03)
    assert exit_day == 1
    assert np.isclose(ret, 0.10)  # side * cum_ret[day1] = -1 * -0.10


def test_leg_exit_sin_disparo_sostiene_hasta_el_ultimo_dia() -> None:
    path = pd.DataFrame({"day": [1, 2, 3, 4], "cum_ret": [0.01, 0.02, 0.01, 0.015]})
    ret, exit_day = leg_exit(path, side=1.0, sigma=0.10, k=1.0, h=4)  # umbral ±0.10, nunca cruza
    assert exit_day == 4
    assert np.isclose(ret, 0.015)


def test_leg_exit_sigma_nan_nunca_dispara() -> None:
    path = pd.DataFrame({"day": [1, 2], "cum_ret": [10.0, -10.0]})  # movimientos enormes
    ret, exit_day = leg_exit(path, side=1.0, sigma=float("nan"), k=1.0, h=2)
    assert exit_day == 2 and np.isclose(ret, -10.0)


def test_leg_exit_path_vacio() -> None:
    ret, exit_day = leg_exit(pd.DataFrame(columns=["day", "cum_ret"]), 1.0, 0.03, 1.0, 5)
    assert ret == 0.0 and exit_day == 5


def test_spread_watchdog_economics_ambas_patas_disparan_temprano() -> None:
    groups = {
        "UP": _sym("2024-01-01", [100, 105, 112]),
        "DOWN": _sym("2024-01-01", [50, 45, 40]),
    }
    day = pd.DataFrame(
        {"sigma20": [0.03, 0.03], "fwd_ret_24h_mxn": [0.10, -0.10]}, index=["UP", "DOWN"]
    )
    w_long = pd.Series([0.5], index=["UP"])
    w_short = pd.Series([0.5], index=["DOWN"])
    r = spread_watchdog_economics(
        groups, day, w_long, w_short, pd.Timestamp("2024-01-01"), h=2, k=1.0
    )
    # UP: cum day1=0.05 ≥ 0.03 → dispara, ret=0.05
    # DOWN: cum day1=-0.10 → signed(-1·cum)=0.10 ≥ 0.03 → dispara, ret=-1·(-0.10)=0.10
    gross_ret = 0.5 * 0.05 + 0.5 * 0.10
    funding = FUNDING_BUFFER * (0.5 * 0.5 + 0.5 * 0.5)  # ambas a día 1 de 2 → fracción 0.5
    esperado = round((gross_ret - ROUNDTRIP * 1.0 - funding) * 100, 4)
    assert np.isclose(r["net_pct"], esperado)
    assert r["long_leg_pct"] == 2.5 and r["short_leg_pct"] == 5.0
    assert r["n_early_exit"] == 2 and r["n_take_profit"] == 2 and r["n_stop_loss"] == 0
    assert r["mean_exit_day"] == 1.0


def test_spread_watchdog_economics_sin_disparo_iguala_hold_completo() -> None:
    """sigma inalcanzable ⇒ el motor colapsa al retorno pleno de H días (mismo costo
    que spread_window_economics con un solo símbolo por pata, gross 1.0)."""
    groups = {
        "UP": _sym("2024-01-01", [100, 101, 102]),
        "DOWN": _sym("2024-01-01", [50, 49.5, 49]),
    }
    day = pd.DataFrame(
        {"sigma20": [10.0, 10.0], "fwd_ret_24h_mxn": [0.0, 0.0]}, index=["UP", "DOWN"]
    )
    w_long = pd.Series([0.5], index=["UP"])
    w_short = pd.Series([0.5], index=["DOWN"])
    r = spread_watchdog_economics(
        groups, day, w_long, w_short, pd.Timestamp("2024-01-01"), h=2, k=1.0
    )
    assert r["n_early_exit"] == 0
    assert r["mean_exit_day"] == 2.0
    # funding prorateado a fracción 1.0 en ambas patas ⇒ colapsa al FUNDING_BUFFER plano
    up_ret = 102 / 100 - 1
    down_ret = -1 * (49 / 50 - 1)
    gross_ret = 0.5 * up_ret + 0.5 * down_ret
    esperado = round((gross_ret - ROUNDTRIP * 1.0 - FUNDING_BUFFER) * 100, 4)
    assert np.isclose(r["net_pct"], esperado)


def test_spread_watchdog_economics_simbolo_ausente_se_omite() -> None:
    groups = {"UP": _sym("2024-01-01", [100, 101])}
    day = pd.DataFrame({"sigma20": [0.03], "fwd_ret_24h_mxn": [0.0]}, index=["UP"])
    w_long = pd.Series([0.5], index=["UP"])
    w_short = pd.Series([0.5], index=["GHOST"])  # nunca existió en groups
    r = spread_watchdog_economics(
        groups, day, w_long, w_short, pd.Timestamp("2024-01-01"), h=1, k=1.0
    )
    assert r["n_legs"] == 1
    assert r["short_leg_pct"] == 0.0
