# infra:local-down — Baja el stack local

Detiene todos los contenedores del stack local. Los datos en DuckDB persisten.

## Parámetros
`$ARGUMENTS` — `--clean` para también eliminar volúmenes Docker.
Si vacío, solo detiene sin limpiar.

## Pasos

1. Si `$ARGUMENTS=--clean`:
   ```bash
   docker compose -f docker-compose.local.yml down -v
   ```
   Advertir: "Los volúmenes Docker serán eliminados."

2. Si vacío:
   ```bash
   docker compose -f docker-compose.local.yml down
   ```

3. Confirmar: `✅ Stack local detenido. Datos DuckDB preservados en ./data/`.

## Notas
- El archivo `data/hermes.duckdb` nunca se toca — está en el host, no en un volumen.
