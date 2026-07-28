"""Tests de harvest_structure (H14 F2a) — estimadores contra verdad teórica,
PIT sin lookahead, falsadores, y la invarianza a permutación como demostración
de referencia (el fixmix real vive en F3; DESIGN_H14 §5.5)."""

import numpy as np
import pandas as pd

from src.lab.harvest_structure import (
    apply_falsadores,
    block_bootstrap_median,
    majority_quintile,
    month_stratum,
    permutation_twin_residual,
    rho1_robust,
    sign_persistence,
    variance_ratio,
    wild_bootstrap_pvalue,
)


def _ar1(rho: float, t: int, seed: int = 7, sigma: float = 0.03) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = np.empty(t)
    x[0] = 0.0
    eps = rng.normal(0, sigma, t)
    for i in range(1, t):
        x[i] = rho * x[i - 1] + eps[i]
    return x


def _vr_teorico(rho: float, q: int) -> float:
    return 1 + 2 * sum((1 - k / q) * rho**k for k in range(1, q))


# ---------- variance ratio ----------

def test_vr_ar1_negativo_contra_teorico() -> None:
    x = _ar1(-0.25, 20_000)
    for q in (2, 5, 10, 28):
        vr, _ = variance_ratio(x, q)
        assert abs(vr - _vr_teorico(-0.25, q)) < 0.05, f"q={q}"


def test_vr_ar1_positivo_contra_teorico() -> None:
    x = _ar1(0.2, 20_000)
    vr, z = variance_ratio(x, 5)
    assert abs(vr - _vr_teorico(0.2, 5)) < 0.05
    assert z > 3  # momentum fuerte con T enorme → z grande


def test_vr_iid_cerca_de_uno() -> None:
    rng = np.random.default_rng(11)
    vr, z = variance_ratio(rng.normal(0, 0.04, 20_000), 28)
    assert abs(vr - 1) < 0.1
    assert abs(z) < 2.5


def test_vr_muestra_corta_devuelve_nan() -> None:
    vr, z = variance_ratio(np.random.default_rng(0).normal(size=50), 28)
    assert np.isnan(vr) and np.isnan(z)


def test_vr_tolera_nans() -> None:
    x = _ar1(-0.2, 5_000)
    x[::7] = np.nan
    vr, _ = variance_ratio(x, 5)
    assert np.isfinite(vr)


# ---------- rho1 / persistencia ----------

def test_rho1_recupera_el_coeficiente() -> None:
    rho, se = rho1_robust(_ar1(-0.3, 20_000))
    assert abs(rho - (-0.3)) < 0.03
    assert 0 < se < 0.02


def test_persistencia_reversion_menor_a_medio() -> None:
    assert sign_persistence(_ar1(-0.5, 10_000)) < 0.45
    assert abs(sign_persistence(_ar1(0.0, 10_000)) - 0.5) < 0.03


# ---------- wild bootstrap ----------

def test_wild_bootstrap_rechaza_reversion_fuerte() -> None:
    rng = np.random.default_rng(3)
    p = wild_bootstrap_pvalue(_ar1(-0.3, 5_000), 5, rng, reps=99)
    assert p < 0.05


def test_wild_bootstrap_no_rechaza_iid() -> None:
    rng = np.random.default_rng(4)
    p = wild_bootstrap_pvalue(rng.normal(0, 0.03, 5_000), 5, np.random.default_rng(5), reps=99)
    assert p > 0.05


# ---------- estratos PIT ----------

def _panel_dos_simbolos() -> pd.DataFrame:
    ts = pd.date_range("2021-01-01", "2021-06-30", freq="D")
    rows = []
    for sym, base in (("AAA", 10.0), ("BBB", 1000.0)):
        for t in ts:
            qv = base
            # AAA explota en volumen en abril — NO debe afectar su quintil de abril
            if sym == "AAA" and t >= pd.Timestamp("2021-04-01"):
                qv = 1e9
            rows.append({"symbol": sym, "ts": t, "close": 1.0, "quote_volume": qv})
    return pd.DataFrame(rows)


def test_month_stratum_sin_lookahead() -> None:
    # con solo 2 símbolos qcut de 5 no aplica → replicamos la lógica con 10 símbolos
    ts = pd.date_range("2021-01-01", "2021-05-31", freq="D")
    rows = []
    for i in range(10):
        sym = f"S{i}"
        for t in ts:
            qv = float(10**i)
            # S0 (el más chico) explota en abril
            if sym == "S0" and t >= pd.Timestamp("2021-04-01"):
                qv = 1e12
            rows.append({"symbol": sym, "ts": t, "close": 1.0, "quote_volume": qv})
    strata = month_stratum(pd.DataFrame(rows))
    abril = strata[(strata["symbol"] == "S0") & (strata["month"] == pd.Period("2021-04"))]
    mayo = strata[(strata["symbol"] == "S0") & (strata["month"] == pd.Period("2021-05"))]
    # abril usa la métrica de marzo (chica) → quintil 1; mayo ya ve la explosión → quintil 5
    assert int(abril["quintile"].iloc[0]) == 1
    assert int(mayo["quintile"].iloc[0]) == 5


def test_majority_quintile() -> None:
    strata = pd.DataFrame(
        {
            "symbol": ["A"] * 3 + ["B"] * 3,
            "month": [pd.Period("2022-01"), pd.Period("2022-02"), pd.Period("2022-03")] * 2,
            "quintile": [5, 5, 1, 2, 2, 2],
        }
    )
    mq = majority_quintile(strata, pd.Timestamp("2022-01-01"), pd.Timestamp("2022-03-31"))
    assert mq["A"] == 5 and mq["B"] == 2


# ---------- bootstrap de bloques / gemelos ----------

def test_block_bootstrap_iid_cubre_uno() -> None:
    rng = np.random.default_rng(6)
    mat = rng.normal(0, 0.03, size=(1_000, 8))
    out = block_bootstrap_median(mat, "vr", 5, np.random.default_rng(8), n_boot=60)
    assert out["lo90"] < 1.0 < out["hi90"]


def test_permutation_twin_residual_iid_cerca_de_cero() -> None:
    rng = np.random.default_rng(9)
    res = permutation_twin_residual(
        rng.normal(0, 0.03, 3_000), 5, np.random.default_rng(10), reps=30
    )
    assert abs(res) < 0.08


def test_permutation_twin_residual_detecta_reversion() -> None:
    res = permutation_twin_residual(_ar1(-0.3, 5_000), 5, np.random.default_rng(12), reps=30)
    assert res < -0.2  # el real revierte; el permutado no → residuo negativo


# ---------- falsadores ----------

def test_falsadores_matan_por_ic_completo() -> None:
    vivo = {"median": 0.9, "lo90": 0.8, "hi90": 1.05}
    muerto = {"median": 1.1, "lo90": 1.02, "hi90": 1.2}
    rho_vivo = {"median": -0.02, "lo90": -0.05, "hi90": 0.01}
    rho_muerto = {"median": 0.03, "lo90": 0.01, "hi90": 0.05}

    v = apply_falsadores(vivo, rho_vivo, vivo)
    assert v["HA"]["pass"] and v["HC"]["pass"] and v["advance_to_F3"]

    v = apply_falsadores(muerto, rho_vivo, vivo)
    assert not v["HA"]["pass"] and not v["advance_to_F3"]

    v = apply_falsadores(vivo, rho_muerto, vivo)
    assert not v["HA"]["pass"]  # ρ₁ también falsifica H-A

    v = apply_falsadores(vivo, rho_vivo, muerto)
    assert v["HA"]["pass"] and not v["HC"]["pass"] and not v["advance_to_F3"]


# ---------- invarianza a permutación (demostración de referencia, §5.5) ----------

def test_fixmix_y_bh_invariantes_a_permutacion_a_f1() -> None:
    """A f=1d el fixmix ∏(1+w·r) y el B&H dependen solo del multiconjunto de
    retornos → cualquier gemelo por permutación es EXACTAMENTE igual al real.
    Guardia para F3 (el motor real debe reproducir esta identidad)."""
    rng = np.random.default_rng(13)
    r = rng.normal(0.001, 0.05, 2_000)
    perm = rng.permutation(r)
    w = 0.5
    fixmix = np.prod(1 + w * r)
    fixmix_p = np.prod(1 + w * perm)
    bh = w * np.prod(1 + r) + (1 - w)
    bh_p = w * np.prod(1 + perm) + (1 - w)
    np.testing.assert_allclose(fixmix, fixmix_p, rtol=1e-12)
    np.testing.assert_allclose(bh, bh_p, rtol=1e-12)
