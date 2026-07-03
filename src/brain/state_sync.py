"""Sync del estado operacional con GCS (política de datos PRD §6).

El brain en Cloud Run es efímero: baja el DuckDB operacional del bucket de
estado al arrancar la corrida y lo sube al terminar (1 corrida/día = sin
concurrencia; el bucket tiene versioning para rollback). El histórico completo
de research vive en LOCAL y jamás depende de este archivo.
"""

import os
from pathlib import Path
from typing import Any

SNAPSHOT_LOCAL = Path(__file__).parent.parent / "dashboard" / "static" / "data" / "snapshot.json"
_DEFAULT_DB = "/tmp/hermes.duckdb"  # noqa: S108 — path efímero del contenedor Cloud Run


def _bucket() -> Any:
    from google.cloud import storage

    name = os.environ.get("HERMES_STATE_BUCKET", "")
    if not name:
        raise RuntimeError("HERMES_STATE_BUCKET no definido — el sync GCS es cloud-only")
    return storage.Client().bucket(name)


def download_state() -> str:
    """Baja gs://<bucket>/hermes.duckdb al HERMES_DUCKDB_PATH local (efímero)."""
    db_path = os.environ.get("HERMES_DUCKDB_PATH", _DEFAULT_DB)
    blob = _bucket().blob("hermes.duckdb")
    if not blob.exists():
        raise RuntimeError(
            "gs://.../hermes.duckdb no existe — sembrar el estado primero "
            "(gcloud storage cp data/hermes.duckdb gs://<state-bucket>/)"
        )
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    blob.download_to_filename(db_path)
    return db_path


def upload_state() -> None:
    """Sube el DuckDB operacional y el snapshot del dashboard al bucket."""
    db_path = os.environ.get("HERMES_DUCKDB_PATH", _DEFAULT_DB)
    bucket = _bucket()
    bucket.blob("hermes.duckdb").upload_from_filename(db_path)
    if SNAPSHOT_LOCAL.exists():
        blob = bucket.blob("snapshot.json")
        blob.cache_control = "no-cache"
        blob.upload_from_filename(str(SNAPSHOT_LOCAL), content_type="application/json")
