"""Tests F6 — vara S1/S2 del one-shot secundario y libro/marks del shadow_spread."""

import numpy as np
import pandas as pd
import pytest

from src.lab.shadow_spread import build_book, mark_book
from src.lab.spread_oneshot import slice_verdict

pytestmark = pytest.mark.unit


def test_slice_verdict_pasa_y_falla() -> None:
    assert slice_verdict(0.5, 0.6)["pasa"] is True
    assert slice_verdict(-0.1, 0.9)["pasa"] is False  # S1 falla
    assert slice_verdict(0.5, 0.5)["pasa"] is False  # S2 exige ≥ 0.55
    assert slice_verdict(None, 0.9)["pasa"] is False  # sin dato = falla


def test_build_book_firmado_y_neutral() -> None:
    day = pd.DataFrame(
        {
            "p": [0.9, 0.8, 0.7, 0.6, 0.55, 0.45, 0.4, 0.3, 0.2, 0.1],
            "sigma20": [0.02] * 10,
        },
        index=[f"S{i}" for i in range(10)],
    )
    book = build_book(day, 5, "ew")
    assert np.isclose(sum(book.values()), 0.0)  # net 0
    assert np.isclose(sum(abs(w) for w in book.values()), 1.0)  # gross 1
    assert book["S0"] > 0 > book["S9"]


def test_mark_book_a_mano() -> None:
    book = {"UP": 0.5, "DOWN": -0.5}
    p0 = {"UP": 100.0, "DOWN": 200.0}
    pt = {"UP": 110.0, "DOWN": 160.0}  # UP +10%, DOWN −20%
    # pnl = 0.5·0.10 + (−0.5)·(−0.20) = 0.15
    assert np.isclose(mark_book(book, p0, pt), 0.15)


def test_mark_book_ignora_simbolos_sin_precio() -> None:
    book = {"A": 0.5, "B": -0.5}
    p0 = {"A": 100.0, "B": 100.0}
    pt = {"A": 120.0}  # B sin precio hoy → solo marca A
    assert np.isclose(mark_book(book, p0, pt), 0.10)
