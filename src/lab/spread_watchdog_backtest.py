"""spread_watchdog_backtest — H13 §14: salida por precio (watchdog) sobre gruls-ivol.

Reutiliza la receta GRU congelada y la construcción de piernas de spread_backtest.py,
pero camina día a día dentro de la ventana de H días y cierra cada posición INDIVIDUAL
en cuanto su retorno propio (signo de la pata ya aplicado) cruza ±k·sigma20 desde su
entrada — profit-target y stop-loss simétricos, por posición, no a nivel de todo el
libro. sigma20 es la MISMA métrica que ya pondera la pierna ivol (spread_leg_weights),
no un porcentaje universal fijo — ver §14.1 (precedente H11: nivel fijo ±3% enterrado
por quedar dentro de la banda de ruido diaria).

Grilla cerrada §14.3: k ∈ {1.0, 1.5, 2.0}. Vara §14.4: la mediana neta 2022+ no debe
quedar por debajo de la mediana neta 2022+ de gruls-ivol sin watchdog (+1.01%/ventana,
reports/h13_spread.json modo ivol, EXPERIMENT_LOG.md 2026-07-13 F4b).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.spread_watchdog_backtest"
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from src.lab import gcs
from src.lab.dataset import extremes_label
from src.lab.h13_eval import FUNDING_BUFFER, ROUNDTRIP, apply_h13_bar, spread_leg_weights
from src.lab.splits import partitions
from src.lab.train import load_panel
from src.lab.window_check import GRU_SPEC_BLOB, H, _eligible_dates, sample_windows, train_mask

TOP_K = 5
MIN_UNIVERSE = 2 * TOP_K
GRID_K = (1.0, 1.5, 2.0)
RUN_TAG = "20260724"
# vara §14.4 — mediana neta 2022+ de gruls-ivol SIN watchdog (fuente: reports/h13_spread.json
# modo ivol, citada en EXPERIMENT_LOG.md 2026-07-13 F4b). No re-derivar de memoria: si este
# número se re-lee de GCS, actualizar la constante con su valor exacto antes de correr §14.4.
GRULS_IVOL_NET_MEDIAN_MODERN = 1.01


def symbol_path(g: pd.DataFrame, pos0: int, h: int) -> pd.DataFrame:
    """Retorno acumulado MXN día a día desde la fila `pos0` (ancla t0) hasta `pos0+h`,
    para UN símbolo ya ordenado por ts. `day` 1..len-1 (day 0 = la ancla, se descarta).
    Shift POSICIONAL (no calendario), igual convención que fwd_ret_24h_mxn/trend_study.
    """
    sub = g.iloc[pos0 : pos0 + h + 1].reset_index(drop=True)
    if len(sub) < 2:
        return pd.DataFrame(columns=["day", "cum_ret"])
    close0, fx0 = float(sub.loc[0, "close"]), float(sub.loc[0, "usdmxn"])
    price_ret = sub["close"] / close0 - 1.0
    fx_ret = (sub["usdmxn"] / fx0 - 1.0).fillna(0.0)
    cum = (1 + price_ret) * (1 + fx_ret) - 1.0
    out = pd.DataFrame({"day": range(len(sub)), "cum_ret": cum.to_numpy()})
    return out.iloc[1:].reset_index(drop=True)


def leg_exit(path: pd.DataFrame, side: float, sigma: float, k: float, h: int) -> tuple[float, int]:
    """Retorno realizado y día de cierre de UNA pata (side=+1 largo, −1 corto): el
    primer día donde el retorno CON SIGNO cruza ±k·sigma, o el último día disponible
    si nunca dispara (sigma inválida/NaN se trata como 'nunca dispara', fallback al
    hold completo — nunca inventa un cierre)."""
    if path.empty:
        return 0.0, h
    signed = side * path["cum_ret"]
    if pd.notna(sigma) and sigma > 0:
        hit = path[(signed >= k * sigma) | (signed <= -k * sigma)]
        if not hit.empty:
            row = hit.iloc[0]
            return float(side * row["cum_ret"]), int(row["day"])
    last = path.iloc[-1]
    return float(side * last["cum_ret"]), int(last["day"])


def spread_watchdog_economics(
    groups: dict[str, pd.DataFrame],
    day: pd.DataFrame,
    w_long: pd.Series,
    w_short: pd.Series,
    t0: pd.Timestamp,
    h: int,
    k: float,
) -> dict[str, Any]:
    """Punto económico del libro neutral con salida por precio, por posición. Costos:
    roundtrip completo por pata (una entrada+salida, cierre temprano o no, igual que
    un hold completo) + funding prorateado por fracción de días efectivamente
    sostenidos (§14.2) — con gross 1.0 y todas las patas sosteniendo el hold completo,
    colapsa exactamente al FUNDING_BUFFER plano de spread_window_economics."""
    legs: list[dict[str, Any]] = []
    for w_series, side in ((w_long, 1.0), (w_short, -1.0)):
        for s, w in w_series.items():
            g = groups.get(s)
            if g is None:
                continue
            pos0 = int(g["ts"].searchsorted(t0))
            if pos0 >= len(g) or g.loc[pos0, "ts"] != t0:
                continue
            path = symbol_path(g, pos0, h)
            sigma = float(day.loc[s, "sigma20"]) if s in day.index else float("nan")
            ret, exit_day = leg_exit(path, side, sigma, k, h)
            legs.append(
                {"symbol": s, "side": side, "w": float(w), "ret": ret, "exit_day": exit_day}
            )

    bench = float(day["fwd_ret_24h_mxn"].mean()) - ROUNDTRIP if len(day) else 0.0
    if not legs:
        return {"net_pct": 0.0, "bench_pct": round(bench * 100, 4), "gross": 0.0, "n_legs": 0}

    gross = float(sum(abs(leg["w"]) for leg in legs))
    gross_ret = float(sum(leg["w"] * leg["ret"] for leg in legs))
    funding = FUNDING_BUFFER * float(sum(leg["w"] * (leg["exit_day"] / h) for leg in legs))
    net = gross_ret - ROUNDTRIP * gross - funding
    long_ret = float(sum(leg["w"] * leg["ret"] for leg in legs if leg["side"] > 0))
    short_ret = float(sum(leg["w"] * leg["ret"] for leg in legs if leg["side"] < 0))
    n_early = sum(1 for leg in legs if leg["exit_day"] < h)
    n_tp = sum(1 for leg in legs if leg["exit_day"] < h and leg["ret"] > 0)
    n_sl = n_early - n_tp
    return {
        "net_pct": round(net * 100, 4),
        "bench_pct": round(bench * 100, 4),
        "long_leg_pct": round(long_ret * 100, 4),
        "short_leg_pct": round(short_ret * 100, 4),
        "gross": round(gross, 4),
        "n_legs": len(legs),
        "n_early_exit": n_early,
        "n_take_profit": n_tp,
        "n_stop_loss": n_sl,
        "mean_exit_day": round(float(sum(leg["exit_day"] for leg in legs) / len(legs)), 2),
    }


def main() -> int:
    from src.lab.nn_trial import NnSpec, _predict, _train, build_sequences

    spec = NnSpec(**json.loads(gcs.bucket().blob(GRU_SPEC_BLOB).download_as_text()))
    panel = extremes_label(load_panel(H), k=TOP_K)
    sig = (
        panel.groupby("symbol", observed=True)["close"]
        .pct_change()
        .rolling(20)
        .std()
        .reset_index(level=0, drop=True)
    )
    panel["sigma20"] = sig
    groups = {
        str(s): g.sort_values("ts").reset_index(drop=True)
        for s, g in panel.groupby("symbol", observed=True)
    }

    x_all, meta = build_sequences(panel, spec)
    meta = meta.merge(
        panel[["symbol", "ts", "sigma20"]], on=["symbol", "ts"], how="left", sort=False
    )
    iteration, _ = partitions(pd.DatetimeIndex(panel["ts"].unique()))
    keep = (meta["ts"].isin(iteration) & meta["fwd_ret_24h_mxn"].notna()).to_numpy()
    x_all, meta = x_all[keep], meta[keep].reset_index(drop=True)
    labeled_mask = meta["y"].notna().to_numpy()

    windows = sample_windows(_eligible_dates())
    print(f"[watchdog] {len(windows)} ventanas (idénticas a window_check/spread, seed 42)")

    per_k: dict[float, list[dict[str, Any]]] = {k: [] for k in GRID_K}
    skipped: list[str] = []
    for t0 in windows:
        day_mask = ((meta["ts"] == t0) & meta["operable"]).to_numpy()
        day = meta[day_mask].set_index("symbol").copy()
        if len(day) < MIN_UNIVERSE:
            skipped.append(str(t0.date()))
            continue
        tr_mask = labeled_mask & train_mask(meta["ts"], t0).to_numpy()
        net = _train(x_all[tr_mask], meta.loc[tr_mask, "y"].to_numpy(), spec)
        day["p"] = _predict(net, x_all[day_mask])
        w_long, w_short = spread_leg_weights(day, TOP_K, "ivol")
        for k in GRID_K:
            r = spread_watchdog_economics(groups, day, w_long, w_short, t0, H, k)
            per_k[k].append({"t0": str(t0.date()), **r})
        base = per_k[GRID_K[0]][-1]
        print(
            f"  {t0.date()} k={GRID_K[0]}: net {base['net_pct']:+.2f}% "
            f"(salidas tempranas {base['n_early_exit']}/{base['n_legs']})"
        )

    ran_at = datetime.now(UTC).isoformat()
    report: dict[str, Any] = {
        "generated": ran_at,
        "protocol": "§14 — watchdog vol-relativo por posición sobre gruls-ivol, vara §14.4",
        "windows_skipped_lt10": skipped,
        "gruls_ivol_net_median_modern": GRULS_IVOL_NET_MEDIAN_MODERN,
    }
    lines = ["# H13 §14 — salida por precio (watchdog) sobre gruls-ivol\n"]
    for k in GRID_K:
        res = per_k[k]
        verdict = apply_h13_bar(res)
        beats = verdict["net_median_modern"] >= GRULS_IVOL_NET_MEDIAN_MODERN
        n_tp = sum(r["n_take_profit"] for r in res)
        n_sl = sum(r["n_stop_loss"] for r in res)
        trial_id = f"watchdog-k{k}-{RUN_TAG}"
        report[str(k)] = {"windows": res, **verdict, "n_take_profit": n_tp, "n_stop_loss": n_sl}
        report[str(k)]["beats_gruls_ivol_median"] = beats
        gcs.upload_json(
            {
                "trial_id": trial_id,
                "kind": "spread_watchdog",
                "k": k,
                "base_model": "nn1-gru-h28 (receta §7.1 intacta, retrain por ventana)",
                "framework": "window_check 40w seed42 · vara §14.4",
                **{key: v for key, v in report[str(k)].items() if key != "windows"},
                "ran_at": ran_at,
            },
            f"experiments/trials/{trial_id}.json",
        )
        lines.append(
            f"## k={k} — {'MEJORA' if beats else 'NO MEJORA'} a gruls-ivol "
            f"(§8.1: {'PASA' if verdict['verdict'] else 'NO PASA'})\n"
            f"2022+: mediana {verdict['net_median_modern']:+.2f}% "
            f"(vs {GRULS_IVOL_NET_MEDIAN_MODERN:+.2f}% sin watchdog) · "
            f"media {verdict['net_mean_modern']:+.2f}% · TP {n_tp} / SL {n_sl}\n"
        )
        print(
            f"[watchdog] k={k}: mediana 2022+ {verdict['net_median_modern']:+.2f} "
            f"(vs {GRULS_IVOL_NET_MEDIAN_MODERN:+.2f}) · TP {n_tp} SL {n_sl} · "
            f"{'MEJORA' if beats else 'NO MEJORA'}"
        )
    gcs.upload_json(report, "reports/h13_watchdog.json")
    gcs.upload_text("\n".join(lines), "reports/h13_watchdog.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
