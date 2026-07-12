"""Entrypoint del Cloud Run Job `hermes-lab` (arco H11).

Modos:
  --selftest   Verifica el entorno del job (env, escritura al bucket) y escribe
               gs://$HERMES_RESEARCH_BUCKET/experiments/selftest.json.
  --spec URI   (Fase D2/E) Corre UN experimento desde un spec JSON en GCS.

Cada task de un sweep resuelve su spec vía CLOUD_RUN_TASK_INDEX.
"""

import argparse
import json
import os
import platform
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Hermes Lab — runner de experimentos H11")
    parser.add_argument("--selftest", action="store_true", help="smoke del entorno del job")
    parser.add_argument("--spec", help="URI GCS del spec JSON del experimento (Fase D2/E)")
    args = parser.parse_args()

    if args.selftest:
        return selftest()
    if args.spec:
        raise NotImplementedError("runner de specs llega en Fase D2/E del arco H11")
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
