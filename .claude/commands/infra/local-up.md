# infra:local-up — Levanta el stack local (Docker + DuckDB + dashboard)

Inicia el entorno de desarrollo local sin GCP, sin costos. Cambia automáticamente a
`HERMES_MODE=local`. Equivalente al modo "Platypai/local" del profesor.

## Parámetros
Ninguno.

## Pasos

1. Verificar que Docker está corriendo: `docker info`.

2. Verificar que `HERMES_MODE=local` (o setearlo si no está definido).

3. Verificar que el directorio `data/` existe; crearlo si no.

4. Verificar que `DEEPSEEK_API_KEY` está configurado.

5. Levantar el stack:
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

6. Verificar que el archivo DuckDB puede crearse en `HERMES_DUCKDB_PATH`.

7. Mostrar resumen:
   ```
   ✅ Stack local activo
   Dashboard : http://localhost:8080
   DuckDB    : ./data/hermes.duckdb
   LLM       : DeepSeek V4 Flash (API)
   Modo      : HERMES_MODE=local (paper trading, sin GCP, $0 costo)
   ```

## Notas
- Los datos en DuckDB persisten en `data/` entre reinicios.
- Para modo cloud: `/infra:local-down` + cambiar `HERMES_MODE=cloud` en `.env`.
