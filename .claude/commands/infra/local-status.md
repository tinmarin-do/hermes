# infra:local-status — Estado del stack local

Muestra el estado de todos los servicios del stack local. Solo lectura.

## Parámetros
Ninguno.

## Pasos

1. Verificar estado de contenedores:
   ```bash
   docker compose -f docker-compose.local.yml ps
   ```

2. Verificar Ollama y modelos disponibles:
   ```bash
   curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]"
   ```

3. Verificar DuckDB:
   - Comprobar que `$HERMES_DUCKDB_PATH` existe y su tamaño.
   - Ejecutar query de health: `SELECT COUNT(*) FROM information_schema.tables`.

4. Verificar dashboard en `http://localhost:8080/health`.

5. Mostrar resumen:
   ```
   ── infra:local-status ────────────────────────────────────
   Ollama    : ✅ running  │ modelos: llama3.2:3b, llama3.1:8b
   Dashboard : ✅ running  │ http://localhost:8080
   DuckDB    : ✅ X.XX MB  │ ./data/hermes.duckdb
   HERMES_MODE: local
   ──────────────────────────────────────────────────────────
   ```
