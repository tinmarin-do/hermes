# infra:local-up — Levanta el stack local (Docker + DuckDB + Ollama)

Inicia el entorno de desarrollo local sin GCP, sin costos. Cambia automáticamente a
`HERMES_MODE=local`. Equivalente al modo "Platypai/local" del profesor.

## Parámetros
Ninguno.

## Pasos

1. Verificar que Docker está corriendo: `docker info`.

2. Verificar que `HERMES_MODE=local` (o setearlo si no está definido).

3. Verificar que el directorio `data/` existe; crearlo si no.

4. Levantar el stack:
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```

5. Esperar a que Ollama esté saludable:
   ```bash
   until curl -s http://localhost:11434/api/tags > /dev/null; do sleep 2; done
   ```

6. Verificar que los modelos están disponibles (llama3.2:3b y llama3.1:8b).
   Si no: `docker compose -f docker-compose.local.yml run ollama-pull`.

7. Verificar que el archivo DuckDB puede crearse en `HERMES_DUCKDB_PATH`.

8. Mostrar resumen:
   ```
   ✅ Stack local activo
   Dashboard : http://localhost:8080
   Ollama    : http://localhost:11434
   DuckDB    : ./data/hermes.duckdb
   Modo      : HERMES_MODE=local (paper trading, sin GCP, $0 costo)
   ```

## Notas
- GPU opcional — Ollama funciona en CPU pero más lento.
- Los datos en DuckDB persisten en `data/` entre reinicios.
- Para modo cloud: `/infra:local-down` + cambiar `HERMES_MODE=cloud` en `.env`.
