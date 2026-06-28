# data:ingest-news — Pull de noticias multi-fuente con scan de prompt injection

Ingesta noticias crudas desde múltiples fuentes (CryptoPanic + RSS), las escanea
contra prompt injection (PRD §8.7.1) y las persiste en la capa Bronze (`bronze_news`).
**Regla de oro:** el texto crudo se guarda y escanea aquí, pero NUNCA fluye a un LLM
de decisión — las capas downstream consumen solo features categóricas.

## Parámetros
`$ARGUMENTS` — formato: `<símbolos> [--sources s1,s2] [--limit N] [--no-scan]`
Ejemplos:
- `BTC/USDT,ETH/USDT` — todas las fuentes configuradas, scan activo
- `BTC/USDT --sources coindesk_rss --limit 20`

## Pasos

1. Parsear símbolos y flags de `$ARGUMENTS`. Default de fuentes: `NEWS_SOURCES` en `.envrc`.

2. Verificar que CryptoPanic tiene `CRYPTOPANIC_API_KEY` (si está en las fuentes).
   Sin key, esa fuente se omite — pero NO se aborta (multi-fuente, §8.7.1).

3. Ejecutar ingesta:
   ```bash
   uv run python -m src.data.cli ingest-news "$SYMBOLS" \
     ${SOURCES:+--sources "$SOURCES"} --limit "${LIMIT:-50}"
   ```
   Pipeline: fetch multi-fuente → length cap → scanner DeBERTa de injection → DuckDB.

4. Reportar: noticias por fuente, total almacenado, cuántas marcadas como injection.

5. Recomendar `/data:cluster-news` como siguiente paso.

## Notas
- Multi-fuente por diseño: CryptoPanic NO es single source of truth.
- Las noticias con `injection_flag=true` se excluyen del clustering downstream.
- El primer run descarga el modelo DeBERTa (~municipal, una vez).
