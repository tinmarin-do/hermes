# data:ingest-bronze — Pull OHLCV raw de ccxt para UN símbolo

Ingesta datos de mercado crudos desde ccxt y los persiste en la capa Bronze.
Una invocación = un símbolo + un timeframe + un rango.

## Parámetros
`$ARGUMENTS` — formato: `<símbolo> <timeframe> [desde] [hasta]`
Ejemplos:
- `BTC/USDT 1h` — últimas 500 velas de 1h
- `BTC/USDT 1h 2026-01-01 2026-06-01` — rango histórico

## Pasos

1. Parsear símbolo, timeframe y rango de `$ARGUMENTS`.

2. Verificar que `<símbolo>` está en `HERMES_ALLOWED_SYMBOLS`. Si no, abortar.

3. Determinar destino según `HERMES_MODE`:
   - `local` → DuckDB en `HERMES_DUCKDB_PATH`, tabla `bronze_ohlcv`
   - `cloud` → Cloud SQL, tabla `bronze_ohlcv`

4. Ejecutar ingesta:
   ```bash
   uv run python -m src.data.bronze.ingest \
     --symbol "$SYMBOL" \
     --timeframe "$TF" \
     --since "$SINCE" \
     --until "$UNTIL"
   ```

5. Reportar: registros ingeridos, rango temporal cubierto, gaps detectados.

6. Recomendar `/data:validate-bronze` como siguiente paso.

## Notas
- No transforma datos — Bronze = raw de ccxt, sin modificar.
- Si el exchange está caído, reintentar con backoff hasta 3 veces.
