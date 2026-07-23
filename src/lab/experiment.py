"""Entrypoint del Cloud Run Job `hermes-lab` (arco H11).

Modos:
  --selftest        Smoke del entorno del job (env, escritura al bucket).
  --baseline        Corre el trial baseline pre-registrado (logística, set v1).
  --spec URI        Corre UN experimento desde un spec JSON en GCS.
  --sweep PREFIX    Cada task toma specs/<PREFIX>/<CLOUD_RUN_TASK_INDEX>.json.

REGLA (DESIGN_H11 §6): nada corre sin registrarse. Cada trial escribe
experiments/trials/<trial_id>.json (una escritura atómica por trial — sin
carreras entre tasks paralelas); n_trials para el DSR = conteo de ese prefijo.
"""

import argparse
import json
import os
import platform
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.cloud import storage


def _bucket() -> "storage.Bucket":
    from google.cloud import storage

    name = os.environ["HERMES_RESEARCH_BUCKET"]
    return storage.Client().bucket(name)


def selftest() -> int:
    """Smoke del laboratorio: entorno + I/O al bucket de research."""
    report = {
        "status": "ok",
        "ts": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "task_index": os.environ.get("CLOUD_RUN_TASK_INDEX"),
        "task_count": os.environ.get("CLOUD_RUN_TASK_COUNT"),
        "bucket": os.environ.get("HERMES_RESEARCH_BUCKET"),
    }
    for mod in ("duckdb", "pandas", "numpy", "sklearn", "lightgbm", "pyarrow", "ccxt"):
        try:
            report[f"import_{mod}"] = __import__(mod).__version__
        except Exception as e:  # noqa: BLE001
            report[f"import_{mod}"] = f"ERROR: {e}"
            report["status"] = "degraded"

    blob = _bucket().blob("experiments/selftest.json")
    blob.upload_from_string(json.dumps(report, indent=2), content_type="application/json")
    print(f"[selftest] {report['status']} → gs://{report['bucket']}/experiments/selftest.json")
    return 0 if report["status"] == "ok" else 1


def _run_and_register(spec_dict: dict[str, Any]) -> int:
    from src.lab import gcs
    from src.lab.train import TrialSpec, run_trial

    spec = TrialSpec(**spec_dict)
    print(f"[experiment] trial={spec.trial_id} model={spec.model} feats={spec.features}")
    result = run_trial(spec)
    result["ran_at"] = datetime.now(UTC).isoformat()
    gcs.upload_json(result, f"experiments/trials/{spec.trial_id}.json")
    print(
        f"[experiment] {spec.trial_id}: F1_bloques={result.get('f1_blocks_mean')}"
        f"±{result.get('f1_blocks_std')} · F1_temporal={result.get('f1_temporal')}"
    )
    for variant in ("backtest_base", "backtest_sl3", "backtest_tp3"):
        bt = result.get(variant)
        if bt and "error" not in bt:
            print(
                f"  {variant}: {bt['mean_daily_net_pct']:+.3f}%/día neto · "
                f"PF {bt.get('profit_factor')} · exceso {bt.get('excess_vs_ew_pct')} · "
                f"Sharpe {bt['sharpe_ann']} · maxDD {bt['max_drawdown_pct']}% · "
                f"PSR {bt['psr_0']} · DSR {bt['dsr']}"
            )
    return 0


def baseline() -> int:
    """Trial pre-registrado: logística sobre el conjunto v1 aprobado en el gate D1."""
    ts = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return _run_and_register(
        {"trial_id": f"baseline-logistic-{ts}", "model": "logistic", "threshold": 0.5}
    )


def from_spec(uri: str) -> int:
    from src.lab import gcs

    path = uri.removeprefix(f"gs://{os.environ['HERMES_RESEARCH_BUCKET']}/")
    spec_dict = json.loads(_bucket().blob(path).download_as_text())
    _ = gcs  # gcs se usa dentro de _run_and_register
    return _run_and_register(spec_dict)


def from_sweep(prefix: str) -> int:
    idx = os.environ.get("CLOUD_RUN_TASK_INDEX", "0")
    path = f"experiments/specs/{prefix}/{idx}.json"
    spec_dict = json.loads(_bucket().blob(path).download_as_text())
    return _run_and_register(spec_dict)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Lab — runner de experimentos H11")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--spec", help="URI GCS del spec JSON")
    parser.add_argument("--sweep", help="prefijo de specs para tasks paralelas")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if args.baseline:
        return baseline()
    if args.spec:
        return from_spec(args.spec)
    if args.sweep:
        return from_sweep(args.sweep)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
