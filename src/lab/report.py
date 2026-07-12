"""Leaderboard del arco H11 — lee experiments/trials/*.json → reports/leaderboard.md."""

import json
import sys
from datetime import UTC, datetime

from src.lab import gcs

META_F1 = 0.60


def main() -> int:
    blobs = gcs.list_blobs("experiments/trials/")
    trials = [json.loads(gcs.bucket().blob(b).download_as_text()) for b in sorted(blobs)]
    if not trials:
        print("[report] sin trials registrados aún")
        return 0

    trials.sort(key=lambda t: t.get("f1_temporal") or 0, reverse=True)
    lines = [
        "# Leaderboard H11 — clasificador binario diario MXN",
        f"\nGenerado: {datetime.now(UTC).isoformat()} · {len(trials)} trials "
        f"(n_trials para DSR) · meta: F1 ≥ {META_F1} en AMBAS validaciones\n",
        "| trial | modelo | F1 bloques (μ±σ) | F1 temporal | meta | %/día base | %/día TP3 "
        "| exceso vs B&H | Sharpe | maxDD | DSR |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in trials:
        fb, fs = t.get("f1_blocks_mean"), t.get("f1_blocks_std")
        ft = t.get("f1_temporal")
        meta = "✅" if (fb or 0) >= META_F1 and (ft or 0) >= META_F1 else "—"
        base, tp3 = t.get("backtest_base", {}), t.get("backtest_tp3", {})
        lines.append(
            f"| {t['trial_id']} | {t.get('model')} | {fb}±{fs} | {ft} | {meta} "
            f"| {base.get('mean_daily_net_pct', '—')} | {tp3.get('mean_daily_net_pct', '—')} "
            f"| {base.get('excess_vs_ew_pct', '—')} "
            f"| {base.get('sharpe_ann', '—')} | {base.get('max_drawdown_pct', '—')} "
            f"| {base.get('dsr', '—')} |"
        )
    gcs.upload_text("\n".join(lines), "reports/leaderboard.md")
    print(f"[report] {len(trials)} trials → reports/leaderboard.md")
    print("\n".join(lines[3:9]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
