# ops:logs — Tail de logs de UN servicio específico

## Parámetros
`$ARGUMENTS` — nombre del servicio: `dashboard | brain | scheduler | all`
Opcional: `--since 1h` para filtrar por tiempo.

## Pasos

1. Determinar fuente de logs según `HERMES_MODE`:
   - `local` → `docker compose -f docker-compose.local.yml logs -f <servicio>`
   - `cloud` → `gcloud logging read "resource.labels.service_name=hermes-<servicio>" --limit=100`
     (vía `/infra:gcloud` sin cost gate — logs son gratis en GCP dentro del free tier)

2. Ejecutar tail formateado con structlog.

3. Filtrar por nivel si se especifica `--level ERROR`.
