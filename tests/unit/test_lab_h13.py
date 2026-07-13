"""Tests de la vara §8.1 y los motores F4/F4b (h13_eval) — números a mano."""

import numpy as np
import pandas as pd
import pytest

from src.lab.h13_eval import (
    FUNDING_28D,
    FUNDING_BUFFER,
    ROUNDTRIP,
    apply_h13_bar,
    spread_leg_weights,
    spread_window_economics,
    tsmom_window_economics,
    vol_scaled_signs,
)

pytestmark = pytest.mark.unit


def _win(t0: str, net: float, bench: float) -> dict[str, float | str]:
    return {"t0": t0, "net_pct": net, "bench_pct": bench}


def test_vara_pasa_caso_limpio() -> None:
    wins = [
        _win("2021-03-01", -2.0, 5.0),  # estrés dentro de tolerancia (≥ −3)
        _win("2022-02-01", 1.5, -4.0),
        _win("2022-08-01", 0.5, -2.0),
        _win("2023-05-01", 2.0, 3.0),
        _win("2024-04-01", 1.2, -1.0),
        _win("2025-06-01", 0.3, 2.0),
    ]
    v = apply_h13_bar(wins)
    assert v["w1"] and v["w2"] and v["w3"] and v["w4"] and v["verdict"]


def test_vara_w4_mata_beta_disfrazada() -> None:
    """Gana en promedio pero pierde SIEMPRE que el mercado cae → W4 falla."""
    wins = [
        _win("2022-02-01", -1.0, -4.0),
        _win("2022-08-01", -0.5, -2.0),
        _win("2023-05-01", 4.0, 6.0),
        _win("2024-04-01", 3.0, 5.0),
    ]
    v = apply_h13_bar(wins)
    assert v["w1"] is True  # mediana y media 2022+ altas
    assert v["w4"] is False and v["verdict"] is False


def test_vara_w2_mata_anio_muerto() -> None:
    wins = [
        _win("2022-02-01", -2.0, -1.0),
        _win("2022-08-01", -1.5, 1.0),
        _win("2023-05-01", 4.0, -1.0),
        _win("2024-04-01", 4.0, -2.0),
    ]
    v = apply_h13_bar(wins)
    assert v["w2"] is False and v["verdict"] is False


def test_vol_scaled_signs_escala_y_capea() -> None:
    idx = ["A", "B", "C"]
    signs = pd.Series([1.0, -1.0, 0.0], index=idx)
    sigma = pd.Series([0.01, 0.02, 0.03], index=idx)
    w = vol_scaled_signs(signs, sigma, sigma_target_ann=0.25, gross_cap=1.0)
    assert w["C"] == 0.0
    # A tiene la mitad de vol que B → |w_A| = 2·|w_B|
    assert w["A"] > 0 > w["B"]
    assert np.isclose(abs(w["A"]) / abs(w["B"]), 2.0)
    assert w.abs().sum() <= 1.0 + 1e-9


def test_vol_scaled_signs_respeta_gross_cap() -> None:
    idx = list("ABCD")
    signs = pd.Series([1.0, 1.0, -1.0, -1.0], index=idx)
    sigma = pd.Series([0.001] * 4, index=idx)  # vol bajísima → pediría gross enorme
    w = vol_scaled_signs(signs, sigma)
    assert np.isclose(w.abs().sum(), 1.0)


def test_tsmom_economics_a_mano() -> None:
    day = pd.DataFrame({"fwd_ret_24h_mxn": [0.10, -0.05]}, index=["A", "B"])
    w = pd.Series([0.5, -0.5], index=["A", "B"])  # net 0, gross 1
    r = tsmom_window_economics(day, w)
    # bruto = 0.5·0.10 + (−0.5)·(−0.05) = 0.075; costos = roundtrip·1 + funding·0
    esperado = (0.075 - ROUNDTRIP * 1.0) * 100
    assert np.isclose(r["net_pct"], round(esperado, 4))
    assert r["net_exposure"] == 0.0 and r["n_long"] == 1 and r["n_short"] == 1


def test_tsmom_funding_solo_sobre_net() -> None:
    day = pd.DataFrame({"fwd_ret_24h_mxn": [0.0, 0.0]}, index=["A", "B"])
    w = pd.Series([0.6, 0.2], index=["A", "B"])  # net 0.8, gross 0.8
    r = tsmom_window_economics(day, w)
    esperado = (-ROUNDTRIP * 0.8 - FUNDING_28D * 0.8) * 100
    assert np.isclose(r["net_pct"], round(esperado, 4))


def test_spread_legs_neutrales_y_ordenadas() -> None:
    day = pd.DataFrame(
        {
            "p": [0.9, 0.8, 0.7, 0.6, 0.55, 0.45, 0.4, 0.3, 0.2, 0.1],
            "sigma20": [0.02] * 10,
            "fwd_ret_24h_mxn": [0.0] * 10,
        },
        index=[f"S{i}" for i in range(10)],
    )
    w_long, w_short = spread_leg_weights(day, 5, "ew")
    assert np.isclose(w_long.sum(), 0.5) and np.isclose(w_short.sum(), 0.5)
    assert set(w_long.index) == {"S0", "S1", "S2", "S3", "S4"}
    assert set(w_short.index) == {"S5", "S6", "S7", "S8", "S9"}


def test_spread_ivol_pondera_inverso() -> None:
    day = pd.DataFrame(
        {
            "p": [0.9, 0.8, 0.7, 0.6, 0.55, 0.45, 0.4, 0.3, 0.2, 0.1],
            "sigma20": [0.01, 0.02, 0.02, 0.02, 0.02] + [0.02] * 5,
            "fwd_ret_24h_mxn": [0.0] * 10,
        },
        index=[f"S{i}" for i in range(10)],
    )
    w_long, _ = spread_leg_weights(day, 5, "ivol")
    assert np.isclose(w_long["S0"] / w_long["S1"], 2.0)  # mitad de vol → doble peso
    assert np.isclose(w_long.sum(), 0.5)


def test_spread_economics_cobra_ambas_piernas() -> None:
    day = pd.DataFrame({"fwd_ret_24h_mxn": [0.10, -0.20]}, index=["UP", "DOWN"])
    w_long = pd.Series([0.5], index=["UP"])
    w_short = pd.Series([0.5], index=["DOWN"])
    r = spread_window_economics(day, w_long, w_short)
    # largo 0.5·0.10 = 0.05 · corto −0.5·(−0.20) = 0.10 · costos roundtrip·1 + buffer
    esperado = (0.05 + 0.10 - ROUNDTRIP * 1.0 - FUNDING_BUFFER) * 100
    assert np.isclose(r["net_pct"], round(esperado, 4))
    assert r["long_leg_pct"] == 5.0 and r["short_leg_pct"] == 10.0
