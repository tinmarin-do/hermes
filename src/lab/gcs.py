"""Helpers GCS del laboratorio H11 — I/O parquet/JSON contra el bucket de research."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from google.cloud import storage

BUCKET_ENV = "HERMES_RESEARCH_BUCKET"


def bucket() -> storage.Bucket:
    return storage.Client().bucket(os.environ[BUCKET_ENV])


def upload_parquet(df: pd.DataFrame, blob_path: str) -> None:
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        df.to_parquet(tmp.name, index=False)
        bucket().blob(blob_path).upload_from_filename(tmp.name)


def read_parquet(blob_path: str) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix=".parquet") as tmp:
        bucket().blob(blob_path).download_to_filename(tmp.name)
        return pd.read_parquet(tmp.name)


def upload_json(obj: dict[str, Any] | list[Any], blob_path: str) -> None:
    bucket().blob(blob_path).upload_from_string(
        json.dumps(obj, indent=2, default=str), content_type="application/json"
    )


def upload_text(text: str, blob_path: str) -> None:
    bucket().blob(blob_path).upload_from_string(text, content_type="text/markdown")


def download_to(blob_path: str, local: str | Path) -> Path:
    local = Path(local)
    local.parent.mkdir(parents=True, exist_ok=True)
    bucket().blob(blob_path).download_to_filename(str(local))
    return local


def list_blobs(prefix: str) -> list[str]:
    return [b.name for b in bucket().list_blobs(prefix=prefix)]


def safe_name(symbol: str) -> str:
    """BTC/USDT → BTC_USDT (nombres de objeto sin slash)."""
    return symbol.replace("/", "_")
