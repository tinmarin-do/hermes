# ops:health — Health check de todos los servicios

Verifica el estado de salud de todos los componentes del sistema.

## Parámetros
Ninguno.

## Pasos

1. Según `HERMES_MODE`:

   **local:**
   - Docker services: `docker compose -f docker-compose.local.yml ps`
   - Dashboard: `curl -s http://localhost:8080/health`
   - Ollama: `curl -s http://localhost:11434/api/tags`
   - DuckDB: query de health sobre `HERMES_DUCKDB_PATH`

   **cloud:**
   - Cloud Run dashboard: `gcloud run services describe hermes-dashboard --region=$GCP_REGION`
   - Cloud SQL: test de conexión
   - Cloud Scheduler: estado de jobs
   - Último run_id en BD y su timestamp

2. Mostrar tabla de estado:
   ```
   ── ops:health ─────────────────────────────────────────────
   Dashboard    : ✅ healthy  (http://localhost:8080)
   Brain/Ollama : ✅ healthy
   Database     : ✅ healthy  (X tablas, X MB)
   Scheduler    : ✅ próxima corrida: 2026-06-26T04:00:00Z
   Kill switch  : ✅ INACTIVO
   Última corrida: hace X horas — ✅ éxito
   ──────────────────────────────────────────────────────────
   ```

3. Si algún componente falla: sugerir el skill de recovery correspondiente.
