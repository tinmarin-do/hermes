"""get_secret — resolución de secretos env-first con fallback a Secret Manager (F6).

Blindaje 2026-07-03: las keys viven SOLO en Secret Manager (una key Bitso se filtró
vía .env). En cloud llegan como secret_key_ref (env del contenedor); en local este
helper las trae de SM vía REST usando ADC, directo a memoria de proceso — jamás a
archivos, stdout ni contexto de sesión.

Uso:
    from src.secrets import get_secret
    api_key = get_secret("DEEPSEEK_API_KEY")   # env → SM hermes-deepseek-api-key
"""

from __future__ import annotations

import os

# env var canónica → secret id en Secret Manager
_SECRET_IDS = {
    "DEEPSEEK_API_KEY": "hermes-deepseek-api-key",
    "BITSO_API_KEY": "hermes-bitso-api-key",
    "BITSO_API_SECRET": "hermes-bitso-api-secret",
    "OPENAI_API_KEY": "hermes-openai-api-key",
    "DB_PASSWORD": "hermes-db-password",
}


def get_secret(name: str, project: str | None = None) -> str:
    """Devuelve el secreto: primero env (cloud/secret_key_ref), luego Secret Manager.

    Cachea en os.environ para no re-pegar a SM en el mismo proceso. Lanza RuntimeError
    si no se puede resolver (jamás devuelve vacío silencioso).
    """
    val = os.environ.get(name, "")
    if val:
        return val

    secret_id = _SECRET_IDS.get(name)
    if secret_id is None:
        raise RuntimeError(f"Secreto desconocido: {name} (no está en _SECRET_IDS)")

    project = (
        project or os.environ.get("GCP_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    )
    if not project:
        raise RuntimeError(f"{name}: sin env ni GCP_PROJECT_ID para ir a Secret Manager")

    import google.auth
    import google.auth.transport.requests
    import requests

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())  # type: ignore[no-untyped-call]
    url = (
        f"https://secretmanager.googleapis.com/v1/projects/{project}"
        f"/secrets/{secret_id}/versions/latest:access"
    )
    resp = requests.get(url, headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"{name}: Secret Manager {resp.status_code} para {secret_id}")

    import base64

    # strip: los one-liners de carga (`echo | gcloud secrets versions add`) dejan un
    # \n final que invalida la firma HMAC del exchange — las keys jamás llevan
    # whitespace legítimo en los bordes.
    val = base64.b64decode(resp.json()["payload"]["data"]).decode().strip()
    os.environ[name] = val  # cache de proceso; jamás persistir a disco
    return val
