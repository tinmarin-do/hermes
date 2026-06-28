# infra:local-status — Estado del stack local

Muestra el estado de todos los servicios del stack local. Solo lectura.

## Parámetros
Ninguno.

## Pasos

1. Verificar estado de contenedores:
   ```bash
   docker compose -f docker-compose.local.yml ps
   ```

2. Verificar DuckDB:
   - Comprobar que `$HERMES_DUCKDB_PATH` existe y su tamaño.
   - Ejecutar query de health: `SELECT COUNT(*) FROM information_schema.tables`.

3. Verificar dashboard en `http://localhost:8080/health`.

4. Verificar conectividad con DeepSeek API (`DEEPSEEK_API_KEY` configurado).

5. Mostrar resumen:
   ```
   ── infra:local-status ────────────────────────────────────
   Dashboard : ✅ running  │ http://localhost:8080
   DuckDB    : ✅ X.XX MB  │ ./data/hermes.duckdb
   LLM       : ✅ DeepSeek V4 Flash (API)
   HERMES_MODE: local
   ──────────────────────────────────────────────────────────
   ```
