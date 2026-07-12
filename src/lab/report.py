"""Leaderboard del arco H11 — lee experiments/trials/*.json → reports/leaderboard.md.

Metas v2 (enmienda §9.2, label rel_median): accuracy > 0.55 en AMBAS validaciones +
profit factor ≥ 1.5 + exceso vs B&H > 0 en el holdout temporal. Los trials 1-8
(label abs_1pct, meta F1 vieja) se conservan por historia; su meta queda "—".
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

from src.lab import gcs

META_ACC = 0.55
META_PF = 1.5


def _meta_v2(t: dict[str, Any]) -> str:
    ab, at = t.get("acc_blocks_mean"), t.get("acc_temporal")
    base = t.get("backtest_base", {})
    pf, exc = base.get("profit_factor"), base.get("excess_vs_ew_pct")
    if t.get("label") != "rel_median" or ab is None or at is None or pf is None or exc is None:
        return "—"
    ok = ab > META_ACC and at > META_ACC and pf >= META_PF and exc > 0
    return "✅" if ok else "—"


def main() -> int:
    blobs = gcs.list_blobs("experiments/trials/")
    trials = [json.loads(gcs.bucket().blob(b).download_as_text()) for b in sorted(blobs)]
    if not trials:
        print("[report] sin trials registrados aún")
        return 0

    trials.sort(key=lambda t: (t.get("acc_temporal") or 0, t.get("f1_temporal") or 0), reverse=True)
    lines = [
        "# Leaderboard H11 — clasificador binario diario MXN",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · {len(trials)} trials "
        f"(n_trials para DSR) · meta v2: acc > {META_ACC} en ambas + PF ≥ {META_PF} "
        f"+ exceso vs B&H > 0 (naive acc = 0.50)\n",
        "| trial | modelo | label | acc bloques (μ±σ) | acc temporal | F1 temp | meta "
        "| %/día base | %/día SL3/TP3 | exceso vs B&H | PF | Sharpe | DSR |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in trials:
        ab, as_ = t.get("acc_blocks_mean"), t.get("acc_blocks_std")
        base = t.get("backtest_base", {})
        var = t.get("backtest_sl3") or t.get("backtest_tp3") or {}
        lines.append(
            f"| {t['trial_id']} | {t.get('model')} | {t.get('label', 'abs_1pct')} "
            f"| {ab}±{as_} | {t.get('acc_temporal', '—')} | {t.get('f1_temporal', '—')} "
            f"| {_meta_v2(t)} "
            f"| {base.get('mean_daily_net_pct', '—')} | {var.get('mean_daily_net_pct', '—')} "
            f"| {base.get('excess_vs_ew_pct', '—')} | {base.get('profit_factor', '—')} "
            f"| {base.get('sharpe_ann', '—')} | {base.get('dsr', '—')} |"
        )
    gcs.upload_text("\n".join(lines), "reports/leaderboard.md")
    print(f"[report] {len(trials)} trials → reports/leaderboard.md")
    print("\n".join(lines[3:9]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
