"""shadow_spread — F6 §9.1b: el libro L/S reconstruido sobre el shadow forward.

El JUEZ PRIMARIO del candidato h13-gruls-ivol. El ledger multi-stream del GRU
(corre desde 2026-07-11) guarda p y precios de TODO el universo por día; este
evaluador reconstruye el libro L/S congelado en cada rebalanceo de la grilla 28d
y lo marca a diario contra los precios del ledger. On-demand, idempotente,
cero cambios al producer.

Exigencia pre-registrada (§9.1b): 2-3 semanas de marks sanos (tracking, sin
anomalías) antes del sign-off — NO significancia estadística (imposible en
semanas y no se pretende).

Corre como job:  gcloud run jobs execute hermes-lab --args="src.lab.shadow_spread"
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.lab import gcs
from src.lab.h13_eval import ROUNDTRIP, spread_leg_weights
from src.lab.shadow_producer import GRU_ID, days_prefix

SPEC_BLOB = "models/h13-gruls-ivol.json"
MIN_UNIVERSE = 10


def build_book(day: pd.DataFrame, top_k: int, mode: str) -> dict[str, float]:
    """Libro L/S como pesos firmados {symbol: w} (largo +, corto −)."""
    w_long, w_short = spread_leg_weights(day, top_k, mode)
    book = {str(s): float(w) for s, w in w_long.items()}
    for s, w in w_short.items():
        book[str(s)] = book.get(str(s), 0.0) - float(w)
    return book


def mark_book(book: dict[str, float], p0: dict[str, float], pt: dict[str, float]) -> float:
    """P&L acumulado del libro desde la formación: Σ w·(P_t/P_0 − 1). Símbolos sin
    precio hoy se marcan al último conocido implícito (se excluyen del mark)."""
    pnl = 0.0
    for s, w in book.items():
        if s in p0 and s in pt and p0[s] > 0:
            pnl += w * (pt[s] / p0[s] - 1.0)
    return pnl


def _sigma20_from_ledger(entries: list[dict[str, Any]], upto: str) -> dict[str, float]:
    """σ diaria (hasta 20 retornos) por símbolo usando SOLO precios del ledger ≤ upto.
    Con ledger corto usa lo disponible (mínimo 5 retornos; si no, NaN → ew fallback)."""
    hist: dict[str, list[float]] = {}
    for e in sorted(entries, key=lambda x: str(x["decision_date"])):
        if str(e["decision_date"]) > upto:
            break
        for s, px in e.get("prices_mxn", {}).items():
            hist.setdefault(s, []).append(float(px))
    out: dict[str, float] = {}
    for s, prices in hist.items():
        rets = np.diff(np.log(prices[-21:]))
        out[s] = float(np.std(rets, ddof=1)) if len(rets) >= 5 else float("nan")
    return out


def main() -> int:
    spec = json.loads(gcs.bucket().blob(SPEC_BLOB).download_as_text())
    entries = [
        json.loads(gcs.bucket().blob(b).download_as_text())
        for b in sorted(gcs.list_blobs(days_prefix(GRU_ID)))
    ]
    if not entries:
        print("[shadow-spread] ledger vacío — nada que evaluar")
        return 1

    top_k, mode = int(spec["top_k"]), str(spec["leg_weighting"])
    book: dict[str, float] = {}
    p0: dict[str, float] = {}
    open_date: str | None = None
    realized = 0.0
    marks: list[dict[str, Any]] = []
    for e in sorted(entries, key=lambda x: str(x["decision_date"])):
        d = str(e["decision_date"])
        prices = {str(s): float(v) for s, v in e.get("prices_mxn", {}).items()}
        if e.get("is_rebalance") and e.get("universe") and len(e["universe"]) >= MIN_UNIVERSE:
            if book:  # cerrar libro anterior al precio de hoy
                realized += mark_book(book, p0, prices) - ROUNDTRIP
            day = pd.DataFrame(e["universe"]).set_index("symbol")
            sig = _sigma20_from_ledger(entries, d)
            day["sigma20"] = [sig.get(str(s), float("nan")) for s in day.index]
            eff_mode = mode if day["sigma20"].notna().all() else "ew"
            book, p0, open_date = build_book(day, top_k, eff_mode), prices, d
            marks.append(
                {
                    "date": d,
                    "event": f"REBALANCE ({eff_mode})",
                    "cum_net_pct": round(realized * 100, 4),
                }
            )
        elif book:
            unreal = mark_book(book, p0, prices) - ROUNDTRIP
            marks.append(
                {
                    "date": d,
                    "event": "mark",
                    "cum_net_pct": round((realized + unreal) * 100, 4),
                }
            )

    report = {
        "spec_id": spec["spec_id"],
        "spec_sha256": spec["sha256"],
        "generated": datetime.now(UTC).isoformat(),
        "ledger_days": len(entries),
        "book_open_since": open_date,
        "book": {s: round(w, 5) for s, w in sorted(book.items())},
        "marks": marks,
        "current_cum_net_pct": marks[-1]["cum_net_pct"] if marks else None,
        "judgment_note": "§9.1b: juez primario; exigencia = 2-3 semanas de marks sanos, "
        "no significancia. Sign-off de Erika = gate final.",
    }
    gcs.upload_json(report, "reports/shadow_spread_h13.json")
    for m in marks[-7:]:
        print(f"[shadow-spread] {m['date']} {m['event']}: acumulado {m['cum_net_pct']:+.2f}%")
    print(
        f"[shadow-spread] libro desde {open_date} · {len(marks)} marks · "
        f"acumulado {report['current_cum_net_pct']}%"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
