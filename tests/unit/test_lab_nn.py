"""Tests fase NN H12 §7 — construcción de secuencias (numpy puro) + GRU (torch).

Los tests de torch se saltan si el extra `nn` no está instalado (CI corre sin él;
la imagen del lab lo trae). Los de secuencias corren siempre.
"""

import numpy as np
import pandas as pd
import pytest

from src.lab.nn_trial import NnSpec, _add_channels, build_sequences


def _panel(days: int = 120, symbols: tuple[str, ...] = ("BTC", "ETH")) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    rows = []
    for sym in symbols:
        close = 100 * np.cumprod(1 + rng.normal(0, 0.02, days))
        ts = pd.date_range("2024-01-01", periods=days, freq="D")
        rows.append(
            pd.DataFrame(
                {
                    "ts": ts,
                    "symbol": sym,
                    "open": close,
                    "high": close * (1 + rng.uniform(0.001, 0.03, days)),
                    "low": close * (1 - rng.uniform(0.001, 0.03, days)),
                    "close": close,
                    "volume": rng.uniform(1e5, 2e5, days),
                    "y": rng.choice([0.0, 1.0, np.nan], days),
                    "fwd_ret_24h_mxn": rng.normal(0, 0.02, days),
                    "operable": True,
                }
            )
        )
    return pd.concat(rows, ignore_index=True)


SPEC = NnSpec(trial_id="t", window=30, epochs=2, hidden=8, batch_size=64)


class TestSequences:
    def test_shapes_and_alignment(self):
        x, meta = build_sequences(_panel(), SPEC)
        assert x.shape[1:] == (30, 3)
        assert len(x) == len(meta)
        # el warmup de canales (vol_ma 20d min 10) + ventana 30 recorta el inicio
        assert meta.groupby("symbol")["ts"].min().min() > pd.Timestamp("2024-01-30")

    def test_windows_are_znormed(self):
        x, _ = build_sequences(_panel(), SPEC)
        np.testing.assert_allclose(x.mean(axis=1), 0.0, atol=1e-4)
        np.testing.assert_allclose(x.std(axis=1), 1.0, atol=1e-3)

    def test_causality_last_row_is_meta_day(self):
        """El último paso de la secuencia i es el día de meta.iloc[i]: editar un día
        FUTURO no cambia la secuencia de t (la ventana solo mira hacia atrás)."""
        panel = _panel(days=100, symbols=("BTC",))
        x1, meta = build_sequences(panel, SPEC)
        cut = meta.iloc[40]["ts"]
        panel2 = panel.copy()
        panel2.loc[panel2["ts"] > cut, "close"] *= 3.0  # shock futuro
        x2, _ = build_sequences(panel2, SPEC)
        np.testing.assert_array_equal(x1[40], x2[40])

    def test_nan_windows_dropped(self):
        panel = _panel(days=100, symbols=("BTC",))
        panel.loc[50, "close"] = np.nan
        x, meta = build_sequences(panel, SPEC)
        assert not np.isnan(x).any()

    def test_short_symbol_skipped(self):
        panel = pd.concat([_panel(days=100, symbols=("BTC",)), _panel(days=20, symbols=("XX",))])
        _, meta = build_sequences(panel, SPEC)
        assert set(meta["symbol"]) == {"BTC"}

    def test_channels_causal_columns(self):
        p = _add_channels(_panel(days=60, symbols=("BTC",)))
        assert {"ret_1d", "hl_range", "vol_rel", "rv_20d"} <= set(p.columns)
        assert p["ret_1d"].isna().iloc[0]  # primer día sin retorno


class TestGru:
    def test_fit_deterministic_and_probabilistic(self):
        torch = pytest.importorskip("torch")
        _ = torch
        from src.lab.nn_trial import _fit_predict_nn

        x, meta = build_sequences(_panel(days=200), SPEC)
        y = (np.arange(len(x)) % 2).astype(float)
        (p1,) = _fit_predict_nn(x, y, [x[:50]], SPEC)
        (p2,) = _fit_predict_nn(x, y, [x[:50]], SPEC)
        np.testing.assert_allclose(p1, p2, atol=1e-6)  # mismo seed → mismo modelo
        assert ((p1 > 0) & (p1 < 1)).all()

    def test_learns_separable_signal(self):
        pytest.importorskip("torch")
        from src.lab.nn_trial import _fit_predict_nn

        rng = np.random.default_rng(3)
        x = rng.normal(0, 1, (600, 30, 3)).astype(np.float32)
        y = (x[:, -1, 0] > 0).astype(float)  # señal en el último paso del canal 0
        spec = NnSpec(trial_id="t", window=30, epochs=30, hidden=8, batch_size=64)
        (p,) = _fit_predict_nn(x, y, [x], spec)
        from sklearn.metrics import roc_auc_score

        assert roc_auc_score(y, p) > 0.9


class TestFrozenArtifact:
    def test_roundtrip_parity(self):
        """Red → artefacto JSON (sin pickle) → red reconstruida: MISMAS predicciones."""
        pytest.importorskip("torch")
        import json

        from src.lab.nn_trial import _predict, _train, artifact_from_net, predict_artifact

        rng = np.random.default_rng(9)
        x = rng.normal(0, 1, (300, 30, 3)).astype(np.float32)
        y = (x[:, -1, 0] > 0).astype(float)
        spec = NnSpec(trial_id="t", window=30, epochs=3, hidden=8, batch_size=64)
        net = _train(x, y, spec)
        art = artifact_from_net(net, spec, {"model_id": "test"})
        art = json.loads(json.dumps(art))  # viaje completo por JSON (como GCS)
        np.testing.assert_allclose(predict_artifact(art, x), _predict(net, x), atol=1e-6)
        assert "sha256" in art and art["kind"] == "gru_seq"
